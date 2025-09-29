
# VOC → SQLite

This repo contains scripts to generate a SQLite database from the PASCAL VOC 2012 dataset.

## Prereqs
- Python 3.9+
- `pip install -r environment.yml`

## Dataset
Download PASCAL VOC 2012 and note the path to the folder that contains:
`Annotations/`, `JPEGImages/`, `ImageSets/`.

## Build the DB
```bash
python voc2sqlite.py --voc_root /path/to/VOC2012 --db data/voc2012.db
