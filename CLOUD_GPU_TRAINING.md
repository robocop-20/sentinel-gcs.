# Hosted GPU training

Use a hosted GPU **only for offline fine-tuning and evaluation**.  The live
camera service stays on the local RTX GPU: that avoids internet latency,
outages, and continuous camera-data egress.

No free hosted GPU is unlimited or guaranteed.  Do not put the live feed,
evidence directory, `.env`, API keys, telemetry credentials, face imagery, or
any sensitive operational data in a hosted notebook.

## Prepare the two uploads

From PowerShell in the project directory:

```powershell
cd C:\Users\ASUS\Downloads\fpv
.\cloud_training\prepare_colab_bundle.ps1
```

This creates `cloud_training\sentinel-port-training-bundle.zip`, containing
only the train/evaluate code.  Create a separate `port-dataset.zip` containing
the approved labelled `images/` and `labels/` directories.  Its layout must be:

```text
images/train, images/val, images/test
labels/train, labels/val, labels/test
```

The dataset must use the fixed labels `0 person`, `1 vessel`, `2 vehicle`, and
`3 container`.  Do not mix data from unlicensed sources or put a person in
both train and held-out test sets.

## Run in a hosted notebook

1. Create a notebook with a GPU runtime (for example, Google Colab).
2. Upload `sentinel-port-training-bundle.zip` and the authorised
   `port-dataset.zip` to that notebook.
3. Run these cells:

```python
!nvidia-smi
!pip -q install ultralytics==8.3.0 pyyaml
!unzip -q sentinel-port-training-bundle.zip -d /content
!unzip -q port-dataset.zip -d /content/port-dataset
!python /content/sentinel/cloud_training/colab_job.py \
  --workspace /content/sentinel \
  --dataset /content/port-dataset \
  --epochs 100 --imgsz 960 --batch -1 \
  --output /content/sentinel-output
```

4. Download only `/content/sentinel-output/best.pt` and
   `/content/sentinel-output/cloud-evaluation.json`.

## Required local release checks

Copy the candidate to a new local candidate folder.  Then run the existing
local benchmark and release gate on the actual RTX 2050 deployment hardware.
The hosted job **cannot** deploy the candidate.  It remains blocked until its
held-out metrics, model hash, local p95 inference latency, and release gate
all pass.  A candidate that fails any check must not replace `yolo11s.pt`.

## What this helps

Hosted GPUs can make model training faster and make it practical to test a
larger training sweep.  They will not fix a stopped phone stream, replace
camera calibration, or make a model accurate without a representative,
authorised labelled dataset.
