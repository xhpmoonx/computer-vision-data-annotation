# openimages_to_sqlite.py
import csv
import sqlite3
from pathlib import Path
from datetime import date

# -------- settings --------
DATA_DIR = Path("data")  # where the CSVs live
OUT_DB = Path("openimages_v7_same_schema.db")
TARGET_IMAGE_COUNT = 17125   # match your VOC DB image count by default
# Use these filenames from the V7 page
BOX_FILES = {
    "train":  DATA_DIR / "train-annotations-bbox.csv",
    "validation": DATA_DIR / "validation-annotations-bbox.csv",
    "test":   DATA_DIR / "test-annotations-bbox.csv",
}

IMAGE_INFO_FILES = {
    "train":  DATA_DIR / "train-images-boxable-with-rotation.csv",
    "validation": DATA_DIR / "validation-images-with-rotation.csv",
    "test":   DATA_DIR / "test-images-with-rotation.csv",
}

CLASS_DESCRIPTIONS = DATA_DIR / "oidv7-class-descriptions-boxable.csv"
DATASET_NAME = "OpenImagesV7 (boxes)"
# --------------------------

SCHEMA = """
PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS Image;
DROP TABLE IF EXISTS DatasetVersion;
DROP TABLE IF EXISTS Annotator;
DROP TABLE IF EXISTS LabelClass;
DROP TABLE IF EXISTS Annotation;
DROP TABLE IF EXISTS splits;

CREATE TABLE Image(
    image_id    INTEGER PRIMARY KEY,
    file_path   TEXT NOT NULL,
    width       INTEGER,
    height      INTEGER
);

CREATE TABLE DatasetVersion(
    version_id  INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    release_date TEXT
);

CREATE TABLE Annotator(
    annotator_id INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    expertise_level TEXT
);

CREATE TABLE LabelClass(
    label_class_id INTEGER PRIMARY KEY,
    name           TEXT NOT NULL
);

CREATE TABLE Annotation(
    annotation_id  INTEGER PRIMARY KEY,
    image_id       INTEGER NOT NULL,
    version_id     INTEGER NOT NULL,
    annotator_id   INTEGER NOT NULL,
    label_class_id INTEGER NOT NULL,
    xmin INTEGER, ymin INTEGER, xmax INTEGER, ymax INTEGER,
    bbox TEXT,
    mask_path TEXT,
    FOREIGN KEY(image_id) REFERENCES Image(image_id),
    FOREIGN KEY(version_id) REFERENCES DatasetVersion(version_id),
    FOREIGN KEY(annotator_id) REFERENCES Annotator(annotator_id),
    FOREIGN KEY(label_class_id) REFERENCES LabelClass(label_class_id)
);

CREATE TABLE splits(
    image_id INTEGER NOT NULL,
    split TEXT,
    PRIMARY KEY(image_id, split),
    FOREIGN KEY(image_id) REFERENCES Image(image_id)
);
"""

def read_class_names(path: Path):
    # CSV columns: LabelMID,DisplayName
    mid_to_name = {}
    with path.open(newline="", encoding="utf-8") as f:
        r = csv.reader(f)
        for row in r:
            if not row: continue
            # some files may include header; skip if looks like header
            if row[0].startswith("/") and len(row) >= 2:
                mid_to_name[row[0]] = row[1]
    return mid_to_name

def iter_image_info(paths_by_split):
    # Columns per spec: ImageID,Subset,OriginalURL,OriginalLandingURL,License,...
    #                   OriginalSize,OriginalMD5,Thumbnail300KURL,Rotation
    for split, path in paths_by_split.items():
        with path.open(newline="", encoding="utf-8") as f:
            r = csv.DictReader(f)
            for row in r:
                yield split, row["ImageID"], row

def iter_boxes(paths_by_split):
    # Columns per spec:
    # ImageID,Source,LabelName,Confidence,XMin,XMax,YMin,YMax,IsOccluded,IsTruncated,IsGroupOf,IsDepiction,IsInside,...
    for split, path in paths_by_split.items():
        with path.open(newline="", encoding="utf-8") as f:
            r = csv.DictReader(f)
            for row in r:
                yield split, row

def choose_images(image_info_iter, limit):
    """Return an ordered dict-like mapping of image_id -> (split, url) up to `limit`."""
    chosen = {}
    for split, img_id, row in image_info_iter:
        if img_id in chosen:
            continue
        # prefer the small thumbnail if available; else original URL
        file_url = row.get("Thumbnail300KURL") or row.get("OriginalURL")
        if not file_url:
            continue
        chosen[img_id] = (split, file_url)
        if len(chosen) >= limit:
            break
    return chosen

def main():
    # 1) sanity check files
    for p in [CLASS_DESCRIPTIONS, *BOX_FILES.values(), *IMAGE_INFO_FILES.values()]:
        if not p.exists():
            raise FileNotFoundError(f"Missing required CSV: {p}")

    # 2) class dictionary
    mid_to_name = read_class_names(CLASS_DESCRIPTIONS)

    # 3) pick N images total across splits (first N encountered)
    picked = choose_images(iter_image_info(IMAGE_INFO_FILES), TARGET_IMAGE_COUNT)

    # 4) build DB
    if OUT_DB.exists():
        OUT_DB.unlink()

    conn = sqlite3.connect(str(OUT_DB))
    conn.executescript(SCHEMA)

    with conn:
        # Seed DatasetVersion + Annotator (dummy)
        conn.execute("INSERT INTO DatasetVersion(version_id,name,release_date) VALUES (1, ?, ?)",
                     (DATASET_NAME, date(2022, 10, 1).isoformat()))
        conn.execute("INSERT INTO Annotator(annotator_id,name,expertise_level) VALUES (1, 'OpenImages', 'verified/mixed')")

        # Insert Image + splits
        # assign integer image IDs in insertion order
        imageid_to_int = {}
        next_img_int = 1
        for oid, (split, url) in picked.items():
            imageid_to_int[oid] = next_img_int
            # width/height unknown here (normalized boxes), so leave NULLs
            conn.execute("INSERT INTO Image(image_id,file_path,width,height) VALUES (?,?,NULL,NULL)",
                         (next_img_int, url))
            conn.execute("INSERT OR IGNORE INTO splits(image_id, split) VALUES (?,?)",
                         (next_img_int, split))
            next_img_int += 1

        # Prepare LabelClass mapping on-the-fly (only classes used in our chosen images)
        label_to_int = {}
        next_label_int = 1

        # Insert Annotations (only for images we've picked)
        ann_pk = 1
        for split, row in iter_boxes(BOX_FILES):
            oid = row["ImageID"]
            img_int = imageid_to_int.get(oid)
            if not img_int:
                continue  # skip boxes for images we didn't select

            mid = row["LabelName"]
            # get/assign integer label id
            if mid not in label_to_int:
                # map MID to display name; fallback to MID
                disp = mid_to_name.get(mid, mid)
                label_to_int[mid] = next_label_int
                conn.execute("INSERT INTO LabelClass(label_class_id, name) VALUES (?,?)",
                             (next_label_int, disp))
                next_label_int += 1

            label_int = label_to_int[mid]

            # Compose bbox string with normalized coords, as your schema allows free TEXT
            # Note: Open Images columns are normalized in [0,1] (per spec)
            xmin = float(row["XMin"]); xmax = float(row["XMax"])
            ymin = float(row["YMin"]); ymax = float(row["YMax"])
            bbox_str = f"{xmin:.6f},{ymin:.6f},{xmax:.6f},{ymax:.6f}"

            conn.execute(
                """INSERT INTO Annotation
                   (annotation_id,image_id,version_id,annotator_id,label_class_id,
                    xmin,ymin,xmax,ymax,bbox,mask_path)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (ann_pk, img_int, 1, 1, label_int,
                 None, None, None, None, bbox_str, None)
            )
            ann_pk += 1

    conn.close()
    print(f"Done. Wrote {OUT_DB} with {len(picked)} images and normalized boxes.")

if __name__ == "__main__":
    main()

