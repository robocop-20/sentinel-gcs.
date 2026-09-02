# Two-class maritime training dataset

This local dataset trains only these YOLO classes:

| ID | Label | Use for |
| --- | --- | --- |
| `0` | `small_boat` | Small watercraft, including rigid inflatables and similar small boats |
| `1` | `cargo_vessel` | Cargo ships and freighters; do not use for dockside containers or cranes |

## Seed data and attribution

This repository's curated seed dataset is derived from
[DatasetShips](https://universe.roboflow.com/visocomputacional/datasetships),
licensed **CC BY 4.0**. It has 4,998 images across cargo-vessel and small-craft
types. The images are stored in the private repository through Git LFS; run
`git lfs pull` after cloning before training.

It is seed data only; add licensed images from the actual deployment port
through a reviewed dataset revision before training a replacement model.

After downloading its **YOLOv11** export and extracting it locally, run:

```powershell
python training\import_datasetships.py --source <extracted-datasetships-folder> --dry-run
python training\import_datasetships.py --source <extracted-datasetships-folder>
```

The importer maps `BULK CARRIER`, `CONTAINER SHIP`, and `GENERAL CARGO` to `cargo_vessel`; it maps `TRAWLER` and `YACHT` to `small_boat`. Its other vessel categories become background examples, so the model does not learn to call every vessel a target. Preserve the required CC BY attribution with the training record.

Place images in `images/<split>` and a matching YOLO label file in
`labels/<split>`. For example, `images/train/harbour_001.jpg` requires
`labels/train/harbour_001.txt`.

An image without a target vessel must still have an empty matching `.txt` file.
Such negative images are required to measure false detections. Do not mix
near-identical frames from the same video sequence across train, validation,
and test splits.

No private operational images, labels, camera addresses, credentials, evidence,
or identity data belong in this dataset or repository.
