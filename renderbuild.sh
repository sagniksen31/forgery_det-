#!/bin/bash
set -e

echo ">>> Installing apt packages manually"

apt-get update
apt-get install -y tesseract-ocr tesseract-ocr-eng poppler-utils

echo ">>> Apt install done"
pip install -r requirements.txt
