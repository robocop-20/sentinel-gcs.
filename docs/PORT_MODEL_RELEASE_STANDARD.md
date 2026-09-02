# Port-model release standard

Status: software pipeline present; release is `BLOCKED_DATASET` until an authorized, representative labelled port dataset exists.

## Scope and classes

The custom maritime deployment classes are `small_boat` and `cargo_vessel`. The runtime normalises both to the canonical `vessel` risk category while preserving the model class in the evidence record. Generic COCO YOLO weights are not a validated maritime-classification model. Training data must document site/camera rights, collection period, sensor/resolution, weather/day/night distribution, distance/scale, occlusion, privacy handling, annotation rules, exclusions, and license in a completed dataset card.

## Data controls

`training/validate_port_dataset.py` requires train/val/test image and YOLO-label trees, normalized boxes, all classes in each split, background negatives, no orphan labels, and no byte-identical cross-split images. Dataset fingerprinting is SHA-256 based. Scene/sequence leakage that is not byte-identical still requires a human grouping audit before release.

## Training and evaluation

1. Complete `training/DATASET_CARD.template.md` and place authorized data under the configured external dataset path.
2. Validate labels and fingerprint the dataset.
3. Train through `training/train_port_model.py` with recorded base weights, seed, hyperparameters, augmentation, library versions, GPU/driver, and dataset fingerprint.
4. Evaluate the untouched test split with `training/evaluate_port_model.py`. Retain its object-match counts, background negatives, confusion/PR/F1 plots and prediction-match JSONL.
5. Run `training/analyze_confidence.py --input reports/vision/held-out-prediction-matches.jsonl --model-sha256 <evaluation hash> --dataset-fingerprint-sha256 <evaluation fingerprint>` to create the reliability diagram, histogram, ECE/MCE and Brier score.
6. Benchmark the exact weights with `training/benchmark_inference.py` on deployment-class hardware.
7. Run `training/release_gate.py`; do not alter thresholds after seeing the test result without a new version and rationale.

Required outputs are overall and per-class precision/recall/F1/AP/mAP50/mAP50-95, confusion matrix, false positives/negatives, background FPPI/positive rate, confidence calibration/ECE, inference p50/p95/p99, throughput, model/dataset hashes, and qualitative failure review. Raw confidence is labelled model confidence until calibration is validated.

## Promotion and rollback

`training/promote_port_model.py` may stage a candidate only after the deterministic gate passes and the evaluation/latency hashes agree. A model manifest records release name/version, class set, weights SHA-256, dataset fingerprint, evaluation report, thresholds, and build environment. Runtime verifies manifest/classes/hash when `REQUIRE_MODEL_MANIFEST=true`. Preserve the prior weights/manifest and perform an atomic configuration rollback if readiness, latency, or false-alarm monitoring regresses.

## Release decision

Approval requires independent review of dataset rights/leakage, all gate results, calibration evidence, failure cases, security scan, and controlled replay. The numeric defaults in the gate are project acceptance targets—not measured claims and not military certification. A port release remains `DEVELOPMENT` until dataset and field evidence are recorded.
