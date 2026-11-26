# Console animations (Lottie JSON)

Played by the guided face scan (`assets/js/guided.js`) with the vendored lottie-web light player
(`assets/vendor/lottie/`, MIT). Paths are set in `configs/config.yaml` → `enrollment.guided.animations`.

| File | When | Origin |
|---|---|---|
| `face-scan.json` | intro before the scan ("turn your head like this"), loops | original, generated for FaceGate |
| `success.json` | all angles captured, plays once | original, generated for FaceGate |

To use a free animation from LottieFiles instead: download it as **Lottie JSON**, check its licence
(free ones are usually under the *Lottie Simple License*), save it here and point the config at it.
The light player does not run expressions, so animations relying on them may render differently.
Missing or broken files are skipped silently (the scan falls back to the built-in check mark).
