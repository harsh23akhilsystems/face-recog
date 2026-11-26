# Spec — `gallery/` (storage and matching)

Keeps enrolled identities and decides who a face belongs to.

## Files
| File | Responsibility |
|---|---|
| `store.py` | `GalleryStore` — SQLite: people, samples, embeddings, events, stats |
| `matcher.py` | `Matcher` — 1:N identification (modes, thresholds, margin); `verify_scores` for 1:1 |

## Database (`store.py`)
Single SQLite file at `paths.database` (default `data/facegate.db`, WAL mode, foreign keys on).

```
people(id TEXT PK, name, employee_id UNIQUE NULL, department, notes, active INT, created_at, updated_at)
samples(id TEXT PK, person_id → people ON DELETE CASCADE, det_score, sharpness, face_px, thumb BLOB NULL, created_at)
embeddings(sample_id → samples ON DELETE CASCADE, model TEXT, dim INT, vector BLOB float32[dim], PK(sample_id, model))
events(id INT PK, ts, person_id → people ON DELETE SET NULL, name, status, score, mode, source, thumb BLOB NULL)
```

- Timestamps: ISO-8601 UTC, seconds precision.
- `thumb`: 112×112 aligned face crop, JPEG (q 92 samples, q 85 events). Omitted for samples when
  `enrollment.store_thumbnails: false` (then `reembed` cannot regenerate that sample).
- `vector`: L2-normalised float32 bytes, one row per (sample, model) — adding a model only needs `reembed`.
- `events.name` is denormalised so the log stays readable after a person is deleted.
- Events older than `events.retention_days` are purged at startup.
- An in-memory `version` counter increments on every write; the matcher rebuilds its index lazily.
- Backup: `sqlite3 data/facegate.db ".backup backup.db"` (or stop the server and copy `data/`).

## Matching (`matcher.py`)
For each model, matrix `G (N×512)` of all **active** people's samples. Query `q`: `s = G·q` (cosine).
Person score = `max` (default) or `mean` of that person's sample scores (`matching.aggregate`).

| Mode | Decision score | Accept if |
|---|---|---|
| `arcface` / `adaface` | that model's person score | ≥ `recognizers.<m>.threshold` |
| `fusion` (default) | mean of all loaded models' person scores | ≥ `matching.fusion_threshold` |
| `strict` | fusion score (reported) | every model picks the **same** person, each ≥ its own threshold |

**Margin (open-set safety):** if the runner-up also clears the threshold and `best − runner_up < matching.margin`,
the result is `uncertain` (best candidate returned but not asserted). Otherwise `match` or `unknown`.

**Fallback (`effective_mode`):** `fusion`/`strict` need ≥ 2 loaded models; a single-model mode needs that model.
Otherwise the first available model's single-model mode is used, and the console shows it.

## Thresholds
Cosine thresholds depend on the dataset and camera. Defaults (0.30) are a conservative start for `buffalo_l`
ArcFace and AdaFace IR-101 on clear images. Calibrate with `make evaluate` (see `src/facegate/SPEC.md` → Evaluation)
and set them in Settings or `configs/config.yaml`.
