#!/usr/bin/env python3
# coco2sqlite_autodiscover.py
import os, re, json, sqlite3, argparse
from pathlib import Path
from datetime import date

try:
    from PIL import Image as PILImage
    HAVE_PIL = True
except Exception:
    HAVE_PIL = False

SCHEMA = """
PRAGMA foreign_keys = ON;
DROP TABLE IF EXISTS Annotation;
DROP TABLE IF EXISTS Annotator;
DROP TABLE IF EXISTS DatasetVersion;
DROP TABLE IF EXISTS LabelClass;
DROP TABLE IF EXISTS Image;
DROP TABLE IF EXISTS splits;

CREATE TABLE Image (
  image_id   INTEGER PRIMARY KEY,
  file_path  TEXT NOT NULL UNIQUE,
  width      INTEGER,
  height     INTEGER
);
CREATE TABLE LabelClass (
  label_class_id INTEGER PRIMARY KEY,
  name           TEXT NOT NULL UNIQUE
);
CREATE TABLE Annotator (
  annotator_id    INTEGER PRIMARY KEY,
  name            TEXT NOT NULL,
  expertise_level TEXT
);
CREATE TABLE DatasetVersion (
  version_id   INTEGER PRIMARY KEY,
  name         TEXT NOT NULL UNIQUE,
  release_date TEXT
);
CREATE TABLE Annotation (
  annotation_id  INTEGER PRIMARY KEY,
  image_id       INTEGER NOT NULL,
  version_id     INTEGER NOT NULL,
  annotator_id   INTEGER NOT NULL,
  label_class_id INTEGER NOT NULL,
  xmin INTEGER, ymin INTEGER, xmax INTEGER, ymax INTEGER,
  bbox           TEXT,
  mask_path      TEXT,
  FOREIGN KEY (image_id)       REFERENCES Image(image_id) ON DELETE CASCADE,
  FOREIGN KEY (version_id)     REFERENCES DatasetVersion(version_id),
  FOREIGN KEY (annotator_id)   REFERENCES Annotator(annotator_id),
  FOREIGN KEY (label_class_id) REFERENCES LabelClass(label_class_id)
);
CREATE TABLE splits (
  image_id  INTEGER NOT NULL,
  split     TEXT CHECK(split IN ('train','val','trainval','test')),
  PRIMARY KEY (image_id, split),
  FOREIGN KEY (image_id) REFERENCES Image(image_id) ON DELETE CASCADE
);
"""

# ---------- discovery helpers ----------
def find_split_dirs(root: Path):
    """Return dict {split: Path} for split folder names train2017/val2017/test2017 found anywhere under root."""
    want = {"train": None, "val": None, "test": None}
    for p in root.rglob("*"):
        if not p.is_dir():
            continue
        name = p.name.lower()
        if name == "train2017":
            want["train"] = p
        elif name == "val2017":
            want["val"] = p
        elif name == "test2017":
            want["test"] = p
    return want

def find_annotations(root: Path):
    """Return paths to instances_train2017.json, instances_val2017.json, image_info_test2017.json if found anywhere."""
    out = {"train": None, "val": None, "test": None}
    for p in root.rglob("*.json"):
        n = p.name.lower()
        if n == "instances_train2017.json":
            out["train"] = p
        elif n == "instances_val2017.json":
            out["val"] = p
        elif n == "image_info_test2017.json":
            out["test"] = p
    return out

def load_json(path: Path):
    if path and path.exists():
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    return None

# ---------- DB helpers ----------
def ensure_static_rows(cur):
    cur.execute("INSERT INTO Annotator(annotator_id, name, expertise_level) VALUES (1,'COCO','crowd')")
    cur.execute("INSERT INTO DatasetVersion(version_id, name, release_date) VALUES (1,'COCO 2017',?)",
                (date(2017,9,1).isoformat(),))

def insert_categories(cur, categories):
    if not categories: return
    for cat in categories:
        cur.execute("INSERT OR IGNORE INTO LabelClass(label_class_id,name) VALUES (?,?)",
                    (int(cat["id"]), cat["name"]))

def insert_image_row(cur, image_id, rel_path, width=None, height=None):
    cur.execute(
        "INSERT OR IGNORE INTO Image(image_id,file_path,width,height) VALUES (?,?,?,?)",
        (int(image_id), rel_path, int(width) if width else None, int(height) if height else None)
    )

def insert_split(cur, image_id, split):
    cur.execute("INSERT OR IGNORE INTO splits(image_id, split) VALUES (?,?)", (int(image_id), split))

def insert_images_from_ann(cur, images, split):
    for im in images:
        image_id = int(im["id"])
        file_name = im["file_name"]
        width = im.get("width")
        height = im.get("height")
        rel_path = f"{split}2017/{file_name}"
        insert_image_row(cur, image_id, rel_path, width, height)
        insert_split(cur, image_id, split)

def insert_images_by_scanning(cur, split_dir: Path, split: str, rel_base: str):
    if not split_dir: return
    for jpg in sorted(split_dir.glob("*.jpg")):
        stem = jpg.stem
        try:
            image_id = int(stem)
        except ValueError:
            continue
        w = h = None
        if HAVE_PIL:
            try:
                with PILImage.open(jpg) as im:
                    w, h = im.size
            except Exception:
                pass
        rel_path = f"{rel_base}/{jpg.name}"
        insert_image_row(cur, image_id, rel_path, w, h)
        insert_split(cur, image_id, split)

def insert_annotations(cur, anns):
    if not anns: return
    cur.execute("SELECT COALESCE(MAX(annotation_id),0) FROM Annotation")
    next_id = int(cur.fetchone()[0]) + 1
    for a in anns:
        x, y, w, h = a["bbox"]
        xmin, ymin = int(x), int(y)
        xmax, ymax = int(x + w), int(y + h)
        cur.execute(
            """INSERT INTO Annotation
               (annotation_id,image_id,version_id,annotator_id,label_class_id,
                xmin,ymin,xmax,ymax,bbox,mask_path)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (next_id, int(a["image_id"]), 1, 1, int(a["category_id"]),
             xmin, ymin, xmax, ymax, json.dumps([x,y,w,h]), None)
        )
        next_id += 1

def build(root: Path, out_db: Path, verbose=True):
    ann_paths = find_annotations(root)
    split_dirs = find_split_dirs(root)

    # Create DB
    conn = sqlite3.connect(out_db)
    cur = conn.cursor()
    cur.executescript(SCHEMA)
    ensure_static_rows(cur)

    # Load JSONs if present
    train_data = load_json(ann_paths["train"])
    val_data   = load_json(ann_paths["val"])
    test_info  = load_json(ann_paths["test"])

    # Categories
    cats = (train_data or val_data or {}).get("categories", [])
    insert_categories(cur, cats)

    # Images via annotations first (has width/height); fall back to scanning folders
    if train_data:
        insert_images_from_ann(cur, train_data["images"], "train")
    elif split_dirs["train"]:
        # compute relative base like "train2017" even if nested (for file_path)
        rel_base = split_dirs["train"].name
        insert_images_by_scanning(cur, split_dirs["train"], "train", rel_base)

    if val_data:
        insert_images_from_ann(cur, val_data["images"], "val")
    elif split_dirs["val"]:
        rel_base = split_dirs["val"].name
        insert_images_by_scanning(cur, split_dirs["val"], "val", rel_base)

    if test_info:
        insert_images_from_ann(cur, test_info["images"], "test")
    elif split_dirs["test"]:
        rel_base = split_dirs["test"].name
        insert_images_by_scanning(cur, split_dirs["test"], "test", rel_base)

    # Annotations
    if train_data and "annotations" in train_data:
        insert_annotations(cur, train_data["annotations"])
    if val_data and "annotations" in val_data:
        insert_annotations(cur, val_data["annotations"])

    conn.commit()

    if verbose:
        for t in ["Image","LabelClass","Annotator","DatasetVersion","Annotation","splits"]:
            cur.execute(f"SELECT COUNT(*) FROM {t}")
            print(f"{t:15s}: {cur.fetchone()[0]}")

    conn.close()

def main():
    ap = argparse.ArgumentParser(description="Build COCO2017 SQLite (auto-discovers folders/JSONs)")
    ap.add_argument("--root", required=True, help="Top folder where you unzipped Kaggle COCO files")
    ap.add_argument("--out_db", default="coco2017_slide.db", help="Output SQLite path")
    args = ap.parse_args()
    root = Path(args.root).expanduser().resolve()
    out_db = Path(args.out_db).expanduser().resolve()
    out_db.parent.mkdir(parents=True, exist_ok=True)
    build(root, out_db)

if __name__ == "__main__":
    main()
