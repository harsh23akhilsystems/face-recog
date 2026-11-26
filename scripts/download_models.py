"""Fetch the SCRFD detector and ArcFace recognizer from InsightFace's ``buffalo_l`` pack.

Only ``det_10g.onnx`` (SCRFD-10GF + 5 landmarks) and ``w600k_r50.onnx`` (ArcFace R50) are kept.
AdaFace is not redistributed as ONNX upstream — convert it with ``scripts/export_adaface_onnx.py``.

LICENCE NOTE: InsightFace's pretrained packs are released for non-commercial research use.
For commercial deployment obtain a licence from InsightFace or train/obtain weights you are
permitted to use. See SECURITY.md.
"""

from __future__ import annotations

import argparse
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path

URL = "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip"
KEEP = ("det_10g.onnx", "w600k_r50.onnx")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=Path("models"))
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    if not args.force and all((args.out / f).exists() for f in KEEP):
        print(f"Models already present in {args.out}: {', '.join(KEEP)}")
        return

    with tempfile.TemporaryDirectory() as tmp:
        zpath = Path(tmp) / "buffalo_l.zip"
        print(f"Downloading {URL} (~280 MB)…")
        urllib.request.urlretrieve(URL, zpath)  # noqa: S310 - fixed https URL
        with zipfile.ZipFile(zpath) as zf:
            for member in zf.namelist():
                name = Path(member).name
                if name in KEEP:
                    with zf.open(member) as src, open(args.out / name, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    print(f"  ✓ {args.out / name}")
    missing = [f for f in KEEP if not (args.out / f).exists()]
    if missing:
        raise SystemExit(f"Archive did not contain: {missing}")


if __name__ == "__main__":
    main()
