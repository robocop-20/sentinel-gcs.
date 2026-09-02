# Port-Specific YOLO11 Fine-Tuning

Fine-tuning is the correct way to add reliable `small_boat` and `cargo_vessel`
detection. An LLM does not improve real-time detector recall and is
intentionally not part of the training or tracking loop.

## Model contract

The custom maritime model has exactly two labels:

| ID | Label | Meaning |
|---:|---|---|
| 0 | `small_boat` | Small fishing, leisure, or work boat |
| 1 | `cargo_vessel` | Cargo ship, bulk carrier, container ship, or general cargo vessel |

## Local data layout

```text
training/datasets/port/
  images/train/  labels/train/
  images/val/    labels/val/
  images/test/   labels/test/
```

Each label is a normalised YOLO line: `class_id center_x center_y width height`.
Use footage representative of the actual port cameras: day/night, rain, glare,
occlusion, multiple distances, small targets, cargo vessels, water glare,
docks, cranes, shoreline clutter, empty berths, and moving vessels. Preserve
the data licence and obtain permission for any camera footage used for training.

Both classes must have labelled instances in **train**, **val**, and
**test**. Split whole camera sequences by camera/time, not adjacent frames, so
near-identical video frames cannot leak from training into evaluation. Copy
`training/DATASET_CARD.template.md` to
`training/datasets/port/DATASET_CARD.md` and record the source, licence,
collection period, camera conditions, exclusions, and split method.

`training/import_datasetships.py` can seed the two-class dataset from a
licensed DatasetShips YOLO export. It maps TRAWLER/YACHT to `small_boat` and
BULK CARRIER/CONTAINER SHIP/GENERAL CARGO to `cargo_vessel`; the other source
classes become explicit background frames. Keep the DatasetShips attribution
and add representative, authorised local port and drone images before release.

## Controlled workflow

```powershell
cd C:\Users\ASUS\Downloads\fpv
.\run_port_training_gpu.ps1 -Epochs 60 -ImageSize 640 -Batch 2
```

The script validates and fingerprints the dataset, trains the candidate,
evaluates held-out precision/recall/F1/AP and false-positive/false-negative
counts, generates confidence calibration/ECE evidence, benchmarks the exact
weights, and applies the deterministic release gate. It does not promote a
failed candidate.

Use the local GPU for training; CPU is appropriate only for a small pipeline
test and will be slow. The installed 4 GB GPU is suitable for a modest YOLO11
model and batch size 2; reduce image size/batch if CUDA reports an out-of-memory
error. Do not deploy `best.pt` directly. Validate it on held-out,
representative port footage, complete a copy of
`training/model-manifest.template.json`, and place the approved model at:

```text
C:\Users\ASUS\Downloads\fpv\models\port\port-yolo.pt
```

Promotion requires a passing `release-gate.json` tied to the exact candidate
model SHA-256. The gate checks held-out overall and per-class precision,
recall, mAP50-95, background false alarms, confidence calibration/ECE/Brier
score, plus measured GPU p95 single-frame latency and throughput.
It cannot be passed by changing a dashboard label or by using an LLM. Adjust
thresholds only through an approved evaluation plan.

The validator records an immutable dataset SHA-256 fingerprint in
`dataset-validation.json`; copy that exact value into
`model-manifest.json`. Promotion also requires the evaluation report and a
local dataset card, so it verifies that the model, dataset, evaluation, and
release gate all belong together:

```powershell
& "D:\Docker\Desktop\resources\bin\docker.exe" compose `
  -f .\docker-compose.yml `
  -f .\docker-compose.gpu.yml `
  -f .\docker-compose.training.gpu.yml `
  --profile training run --rm trainer training/promote_port_model.py `
  --model training/runs/port-yolo11/weights/best.pt `
  --manifest training/model-manifest.json `
  --evaluation-report training/runs/port-yolo11/evaluation.json `
  --gate-report training/runs/port-yolo11/release-gate.json
```

Then configure `YOLO_MODEL=/models/port/port-yolo.pt` and restart the vision
vessel. Sentinel normalises both maritime labels to the canonical `vessel` risk
category while retaining the original model label for audit and review.

## LLM boundary

The optional Gemini/Grok/OpenRouter LLM is not a detector, trainer, tracker, or
alert authority. It can only provide an advisory review of approved object
evidence after deterministic rules produce an event. Camera-derived pixels are
not sent externally unless the operator explicitly enables and approves that
separate egress path.
