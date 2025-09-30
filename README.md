# computer-vision-data-annotation

Toolkit to turn popular computer‑vision datasets (e.g., **PASCAL VOC 2012**, **COCO**, **Open Images**) into a compact **SQLite** database for fast exploration, training data curation, and experiment reproducibility.

> Repository: `xhpmoonx/computer-vision-data-annotation`

---

## Why SQLite?

* **Portable** single file you can version, diff, and ship.
* **Fast querying** with SQL (filter by class, area, crowd flags, splits, etc.).
* **Interoperable** with pandas, DuckDB, Polars, and most ML stacks.

---

## Features

* Parse canonical dataset structures (VOC / COCO / Open Images).
* Normalize annotations into relational tables (images, annotations, categories, splits, attributes).
* Export to a single `dataset.sqlite` with indices.
* Utilities for quick EDA (class distribution, bbox stats) and split creation.

> Current folders in this repo suggest per‑format utilities live under `VOC/`, `COCO/`, and `OpenImage/`.

---

## Repository layout

```
COCO/          # COCO → SQLite utilities
OpenImage/     # Open Images → SQLite utilities
VOC/           # PASCAL VOC → SQLite utilities
```

*Exact scripts and entry points may evolve; see each folder’s README or module docstrings.*

---

## Getting started

### Prerequisites

* Python 3.10+
* A virtual environment (recommended)

> Typical dependencies for dataset parsing include: `pandas`, `numpy`, `tqdm`, `pyyaml`, `lxml` or `xmltodict` (for VOC), and standard `sqlite3` (bundled with Python). Install the project’s exact requirements once a `requirements.txt` is provided.

### Install

```bash
# 1) Clone
git clone https://github.com/xhpmoonx/computer-vision-data-annotation.git
cd computer-vision-data-annotation

# 2) Create & activate a venv
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 3) Install deps (placeholder — if a requirements.txt is added)
# pip install -r requirements.txt
```

---

## Quick start

Below are **reference workflows** you can adapt to your scripts under `VOC/`, `COCO/`, and `OpenImage/`.

### A) Convert PASCAL VOC → SQLite (example flow)

```bash
python VOC/convert_voc_to_sqlite.py \
  --voc-root /path/to/VOC2012 \
  --out data/voc2012.sqlite \
  --include-segmentation  # optional
```

**Expected tables (typical):** `images`, `annotations`, `categories`, `splits`, `segmentation`.

### B) Convert COCO → SQLite (example flow)

```bash
python COCO/convert_coco_to_sqlite.py \
  --ann train2017.json \
  --images /path/to/train2017 \
  --out data/coco_train.sqlite
```

### C) Convert Open Images → SQLite (example flow)

```bash
python OpenImage/convert_openimages_to_sqlite.py \
  --root /path/to/open-images \
  --subset train \
  --out data/openimages_train.sqlite
```

> If your script names/options differ, update these commands to match the utilities in each folder.

---

## Example: query your SQLite dataset

Use plain SQL or your favorite dataframe library.

```python
import sqlite3
import pandas as pd

con = sqlite3.connect("data/voc2012.sqlite")

# Top 10 classes by annotation count
q = """
SELECT c.name, COUNT(*) AS n
FROM annotations a
JOIN categories c ON c.id = a.category_id
GROUP BY c.name
ORDER BY n DESC
LIMIT 10;
"""
print(pd.read_sql_query(q, con))

# Get all images that contain both 'person' and 'dog'
q = """
WITH per_img AS (
  SELECT image_id, COUNT(DISTINCT c.name) AS k
  FROM annotations a
  JOIN categories c ON c.id = a.category_id
  WHERE c.name IN ('person','dog')
  GROUP BY image_id
)
SELECT i.file_name, i.width, i.height
FROM images i
JOIN per_img p ON p.image_id = i.id
WHERE p.k = 2;
"""
print(pd.read_sql_query(q, con))
```

---
