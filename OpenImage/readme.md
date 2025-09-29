# OpenImage

OpenImage is a project for image annotation and dataset preparation using the [Google Open Images Dataset](https://storage.googleapis.com/openimages/web/index.html).  
It provides scripts and CSVs for converting bounding-box annotations into a SQLite database and other formats.

---

## 📦 Dataset

This repo includes CSVs from Open Images (V7):

- `oidv7-class-descriptions-boxable.csv`
- `train-annotations-bbox.csv`
- `validation-annotations-bbox.csv`
- `test-annotations-bbox.csv`
- `train-images-boxable-with-rotation.csv`
- `validation-images-with-rotation.csv`
- `test-images-with-rotation.csv`

⚠️ Some of these are very large (100MB+). They are stored using **[Git LFS](https://git-lfs.com/)**.  

### Cloning the repo

Make sure you have Git LFS installed before cloning:

```bash
git lfs install
git clone https://github.com/your-username/computer-vision-data-annotation.git
cd computer-vision-data-annotation
git lfs pull
