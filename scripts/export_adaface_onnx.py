"""Convert an official AdaFace PyTorch checkpoint (``.ckpt``) to ONNX for FaceGate.

AdaFace (https://github.com/mk-minchul/AdaFace, MIT licence) publishes PyTorch-Lightning
checkpoints such as ``adaface_ir101_webface12m.ckpt`` / ``adaface_ir50_ms1mv2.ckpt``. FaceGate serves
every model through ONNX Runtime, so we rebuild the IR backbone here (same module names as
``net.py`` so ``load_state_dict(strict=True)`` proves the architecture matches), load the weights,
and export a dynamic-batch ONNX graph that outputs the 512-d embedding.

Usage::

    make install-export          # one-off: torch (CPU) + onnx
    .venv/bin/python scripts/export_adaface_onnx.py --ckpt ~/Downloads/adaface_ir101_webface12m.ckpt \
        --arch ir_101 --out models/adaface_ir101_webface12m.onnx

Use ``--random-init`` to export an untrained network (CI / smoke tests only).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import torch
from torch import nn


class Flatten(nn.Module):
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return x.view(x.size(0), -1)


class BasicBlockIR(nn.Module):
    """Improved-residual block used by IR-18/34/50/100 in AdaFace's ``net.py``."""

    def __init__(self, in_channel: int, depth: int, stride: int) -> None:
        super().__init__()
        if in_channel == depth:
            self.shortcut_layer = nn.MaxPool2d(1, stride)
        else:
            self.shortcut_layer = nn.Sequential(
                nn.Conv2d(in_channel, depth, (1, 1), stride, bias=False), nn.BatchNorm2d(depth)
            )
        self.res_layer = nn.Sequential(
            nn.BatchNorm2d(in_channel),
            nn.Conv2d(in_channel, depth, (3, 3), (1, 1), 1, bias=False),
            nn.BatchNorm2d(depth),
            nn.PReLU(depth),
            nn.Conv2d(depth, depth, (3, 3), stride, 1, bias=False),
            nn.BatchNorm2d(depth),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.res_layer(x) + self.shortcut_layer(x)


UNITS = {"ir_18": [2, 2, 2, 2], "ir_34": [3, 4, 6, 3], "ir_50": [3, 4, 14, 3], "ir_101": [3, 13, 30, 3]}
CHANNELS = [(64, 64), (64, 128), (128, 256), (256, 512)]


class IRBackbone(nn.Module):
    def __init__(self, arch: str) -> None:
        super().__init__()
        if arch not in UNITS:
            raise ValueError(f"Unsupported arch {arch}; choose from {sorted(UNITS)}")
        self.input_layer = nn.Sequential(nn.Conv2d(3, 64, (3, 3), 1, 1, bias=False), nn.BatchNorm2d(64), nn.PReLU(64))
        modules: list[nn.Module] = []
        for (cin, depth), n in zip(CHANNELS, UNITS[arch], strict=True):
            modules.append(BasicBlockIR(cin, depth, 2))
            modules.extend(BasicBlockIR(depth, depth, 1) for _ in range(n - 1))
        self.body = nn.Sequential(*modules)
        self.output_layer = nn.Sequential(
            nn.BatchNorm2d(512),
            nn.Dropout(0.4),
            Flatten(),
            nn.Linear(512 * 7 * 7, 512),
            nn.BatchNorm1d(512, affine=False),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.output_layer(self.body(self.input_layer(x)))
        # AdaFace returns (embedding / norm, norm); FaceGate L2-normalises itself, so export the raw vector.
        return x


def load_checkpoint(model: nn.Module, ckpt_path: Path) -> None:
    ckpt = torch.load(ckpt_path, map_location="cpu", weights_only=False)
    state = ckpt.get("state_dict", ckpt)
    # Lightning wraps the backbone as `model.`; strip it. Head weights (`head.kernel`) are ignored.
    state = {k[6:]: v for k, v in state.items() if k.startswith("model.")} or state
    model.load_state_dict(state, strict=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ckpt", type=Path, help="AdaFace .ckpt file")
    ap.add_argument("--arch", default="ir_101", choices=sorted(UNITS))
    ap.add_argument("--out", type=Path, default=Path("models/adaface_ir101_webface12m.onnx"))
    ap.add_argument("--opset", type=int, default=17)
    ap.add_argument("--random-init", action="store_true", help="export untrained weights (testing only)")
    args = ap.parse_args()

    model = IRBackbone(args.arch).eval()
    if args.random_init:
        print("WARNING: exporting random weights — embeddings will be meaningless.")
    elif args.ckpt:
        load_checkpoint(model, args.ckpt)
    else:
        ap.error("--ckpt is required (or pass --random-init for a smoke test)")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    dummy = torch.randn(2, 3, 112, 112)
    torch.onnx.export(
        model,
        dummy,
        str(args.out),
        input_names=["input"],
        output_names=["embedding"],
        dynamic_axes={"input": {0: "batch"}, "embedding": {0: "batch"}},
        opset_version=args.opset,
        dynamo=False,
    )

    # Parity check: ONNX Runtime must reproduce PyTorch to within float tolerance.
    import onnxruntime as ort

    sess = ort.InferenceSession(str(args.out), providers=["CPUExecutionProvider"])
    with torch.no_grad():
        ref = model(dummy).numpy()
    got = sess.run(None, {"input": dummy.numpy()})[0]
    err = float(np.abs(ref - got).max())
    print(f"Exported {args.out} ({args.arch}); max |torch - onnx| = {err:.2e}")
    if err > 1e-3:
        raise SystemExit("Parity check failed")


if __name__ == "__main__":
    main()
