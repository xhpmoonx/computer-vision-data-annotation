# voc2sqlite.py  (schema-aligned)
import argparse
import sqlite3
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import date

VOC_CLASSES = [
    "aeroplane","bicycle","bird","boat","bottle","bus","car","cat","chair",
    "cow","diningtable","dog","horse","motorbike","person","pottedplant",
    "sheep","sofa","train","tvmonitor"
]

SCHEMA = """
PRAGMA foreign_keys = ON;

-- Drop old objects first to avoid FK issues if re-running
DROP TABLE IF EXISTS splits;
DROP TABLE IF EXISTS segments;         -- deprecated by Annotation.mask_path
DROP TABLE IF EXISTS objects;          -- replaced by Annotation
DROP TABLE IF EXISTS images;           -- replaced by Image

-- Slide schema + helpful lookups
DROP TABLE IF EXISTS Experiment;
DROP TABLE IF EXISTS Annotation;
DROP TABLE IF EXISTS Annotator;
DROP TABLE IF EXISTS DatasetVersion;
DROP TABLE IF EXISTS LabelClass;
DROP TABLE IF EXISTS Image;

CREATE TABLE Image (
  image_id   INTEGER PRIMARY KEY,
  file_path  TEXT NOT NULL UNIQUE,
  width      INTEGER,
  height     INTEGER
);

CREATE TABLE DatasetVersion (
  version_id   INTEGER PRIMARY KEY,
  name         TEXT NOT NULL UNIQUE,
  release_date TEXT
);

CREATE TABLE Annotator (
  annotator_id   INTEGER PRIMARY KEY,
  name           TEXT NOT NULL,
  expertise_level TEXT
);

CREATE TABLE LabelClass (
  label_class_id INTEGER PRIMARY KEY,
  name           TEXT NOT NULL UNIQUE
);

CREATE TABLE Annotation (
  annotation_id  INTEGER PRIMARY KEY,
  image_id       INTEGER NOT NULL,
  version_id     INTEGER NOT NULL,
  annotator_id   INTEGER NOT NULL,
  label_class_id INTEGER NOT NULL,
  xmin INTEGER, ymin INTEGER, xmax INTEGER, ymax INTEGER,
  bbox           TEXT,       -- optional handy JSON string like "xmin,ymin,xmax,ymax"
  mask_path      TEXT,       -- SegmentationClass/<stem>.png if present
  FOREIGN KEY (image_id)       REFERENCES Image(image_id) ON DELETE CASCADE,
  FOREIGN KEY (version_id)     REFERENCES DatasetVersion(version_id),
  FOREIGN KEY (annotator_id)   REFERENCES Annotator(annotator_id),
  FOREIGN KEY (label_class_id) REFERENCES LabelClass(label_class_id)
);

-- Keep splits because they’re useful operationally
DROP TABLE IF EXISTS splits;
CREATE TABLE splits (
  image_id  INTEGER NOT NULL,
  split     TEXT CHECK(split IN ('train','val','trainval','test')),
  PRIMARY KEY (image_id, split),
  FOREIGN KEY (image_id) REFERENCES Image(image_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_annot_image ON Annotation(image_id);
CREATE INDEX IF NOT EXISTS idx_annot_label ON Annotation(label_class_id);
CREATE INDEX IF NOT EXISTS idx_splits_split ON splits(split);
"""

def parse_annotation(xml_path: Path):
    tree = ET.parse(xml_path)
    root = tree.getroot()

    filename = root.findtext("filename")
    # some VOC XMLs omit folder; not required
    size = root.find("size")
    width = int(size.findtext("width")) if size is not None else None
    height = int(size.findtext("height")) if size is not None else None

    objs = []
    for obj in root.findall("object"):
        name = (obj.findtext("name") or "").strip()
        b = obj.find("bndbox")
        if b is not None:
            xmin = int(float(b.findtext("xmin"))); ymin = int(float(b.findtext("ymin")))
            xmax = int(float(b.findtext("xmax"))); ymax = int(float(b.findtext("ymax")))
        else:
            xmin = ymin = xmax = ymax = None
        objs.append((name, xmin, ymin, xmax, ymax))
    return filename, width, height, objs

def read_split_ids(imagesets_main: Path, split_name: str):
    f = imagesets_main / f"{split_name}.txt"
    ids = set()
    if f.exists():
        ids = {line.strip() for line in f.read_text().splitlines() if line.strip()}
    return ids

def build_db(voc_root: Path, db_path: Path):
    ann_dir = voc_root / "Annotations"
    img_dir = voc_root / "JPEGImages"
    seg_cls_dir = voc_root / "SegmentationClass"
    imagesets_main = voc_root / "ImageSets" / "Main"

    if not ann_dir.exists() or not img_dir.exists():
        raise FileNotFoundError("Expected VOC2012 structure with Annotations/ and JPEGImages/ present.")

    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.executescript(SCHEMA)

    with conn:
        # Seed LabelClass
        for i, cls in enumerate(VOC_CLASSES, start=1):
            conn.execute("INSERT INTO LabelClass(label_class_id, name) VALUES(?,?)", (i, cls))
        # Seed DatasetVersion (VOC2012)
        conn.execute(
            "INSERT INTO DatasetVersion(version_id, name, release_date) VALUES (?,?,?)",
            (1, "VOC2012", "2012-05-11")
        )
        # Seed a system annotator (since VOC has no per-annotator ids)
        conn.execute(
            "INSERT INTO Annotator(annotator_id, name, expertise_level) VALUES (?,?,?)",
            (1, "VOC System", "N/A")
        )

        # Pre-read splits
        split_names = ["train", "val", "trainval", "test"]
        split_idsets = {s: read_split_ids(imagesets_main, s) for s in split_names}

        # Process all annotations
        xml_files = sorted(ann_dir.glob("*.xml"))
        for xmlf in xml_files:
            filename, width, height, objs = parse_annotation(xmlf)
            if not filename:
                filename = f"{xmlf.stem}.jpg"
            img_path = img_dir / filename

            # Insert Image
            conn.execute(
                "INSERT INTO Image (file_path, width, height) VALUES (?,?,?)",
                (str(img_path), width, height)
            )
            image_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            # Insert splits
            stem = Path(filename).stem
            for sname, idset in split_idsets.items():
                if stem in idset:
                    conn.execute("INSERT OR IGNORE INTO splits (image_id, split) VALUES (?,?)", (image_id, sname))

            # mask path (semantic). Same for all objects in that image.
            mask_path = seg_cls_dir / f"{stem}.png"
            mask_str = str(mask_path) if mask_path.exists() else None

            # Insert one Annotation per object
            for (name, xmin, ymin, xmax, ymax) in objs:
                # map class name -> label_class_id (fallback None if unknown)
                row = conn.execute("SELECT label_class_id FROM LabelClass WHERE name=?", (name,)).fetchone()
                if row is None:
                    # unseen class name: create on-the-fly
                    conn.execute("INSERT INTO LabelClass(name) VALUES (?)", (name,))
                    label_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                else:
                    label_id = row[0]

                bbox_str = None
                if None not in (xmin, ymin, xmax, ymax):
                    bbox_str = f"{xmin},{ymin},{xmax},{ymax}"

                conn.execute(
                    """INSERT INTO Annotation
                       (image_id, version_id, annotator_id, label_class_id,
                        xmin, ymin, xmax, ymax, bbox, mask_path)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (image_id, 1, 1, label_id, xmin, ymin, xmax, ymax, bbox_str, mask_str)
                )

    conn.close()
    print(f"Done. SQLite database created at: {db_path}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Load PASCAL VOC2012 into SQLite (slide-aligned schema)")
    ap.add_argument("--voc_root", required=True, help="Path to VOC2012 (contains Annotations/, JPEGImages/, ImageSets/...)")
    ap.add_argument("--db", default="voc2012.db", help="Output SQLite DB")
    args = ap.parse_args()

    build_db(Path(args.voc_root).expanduser().resolve(),
             Path(args.db).expanduser().resolve())
