# COCO → SQLite

This repo contains a single script to generate a SQLite database from the **COCO 2017** dataset.  
The schema mirrors our OpenImages-style database (`Image`, `LabelClass`, `Annotation`, `splits`, etc.).

## Prereqs
- Python 3.9+ (no extra packages required)

## Dataset
Download **COCO 2017** from [Kaggle](https://www.kaggle.com/datasets/awsaf49/coco-2017-dataset)  
and unzip so the folder contains at least:


## Contents

- **`coco2017_slide.db`**  
  A pre-processed SQLite database version of the COCO 2017 annotations.  
  This file is tracked with [Git LFS](https://git-lfs.github.com/) due to its large size.

## Requirements

If you are cloning this repository for the first time, make sure you have Git LFS installed:

```bash
git lfs install
git lfs pull
