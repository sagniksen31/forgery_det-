import os
import re
from typing import Dict, Any, List, Tuple

import PyPDF2
from pikepdf import Pdf
from hashlib import sha256
from PIL import Image


import shutil
import pytesseract

# Auto-detect tesseract on system
tess_cmd = shutil.which("tesseract")
if tess_cmd:
    pytesseract.pytesseract.tesseract_cmd = tess_cmd
else:
    raise RuntimeError("Tesseract not installed on server")

# # Set Tesseract OCR path
# pytesseract.pytesseract.tesseract_cmd = (
#     r"C:\\Users\\saswa\\AppData\\Local\\Programs\\Tesseract-OCR\\tesseract.exe"
# )

# # Poppler path for pdf2image (your system path)
POPLER_PATH = None
# )

# -------------------------
# Reference Template Fingerprint
# -------------------------
REFERENCE_META = {
    "Producer": "Prince 15.1 (www.princexml.com)",
    "Title": "Credential Renderer",
    "PageSizePts": (792, 612),
    "ExpectedImageCount": 2,
    "ExpectedFonts": [
        "CormorantGaramond-BoldItalic",
        "Charm-Bold"
    ]
}

SUSPICIOUS_KW = [
    "photoshop", "microsoft word", "word", "canva",
    "wps", "screenshot", "mobile", "iphone", "android"
]

MIN_FILE_SIZE = 5 * 1024
MAX_FILE_SIZE = 15 * 1024 * 1024

# -------------------------
# Utility Functions
# -------------------------

def compute_sha256(path: str) -> str:
    h = sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_pdf_metadata_pypdf(path: str) -> Dict[str, Any]:
    try:
        reader = PyPDF2.PdfReader(path)
        return {k: str(v) for k, v in (reader.metadata or {}).items()}
    except:
        return {}


def extract_fonts_pike(path: str) -> List[str]:
    fonts = []
    try:
        pdf = Pdf.open(path)
        for page in pdf.pages:
            resources = page.get("/Resources")
            if not resources:
                continue
            fonts_dict = resources.get("/Font")
            if not fonts_dict:
                continue
            for _, font_ref in fonts_dict.items():
                try:
                    obj = font_ref.get_object()
                    base_font = str(obj.get("/BaseFont"))
                    if "+" in base_font:
                        base_font = base_font.split("+")[1]
                    fonts.append(base_font)
                except:
                    continue
    except:
        pass
    return list(dict.fromkeys(fonts))


def count_images_and_ppi(path: str) -> Tuple[int, List[Tuple[int,int,int]]]:
    try:
        pdf = Pdf.open(path)
        count = 0
        info = []
        for page in pdf.pages:
            try:
                imgs = list(page.images.items())
            except:
                imgs = []
            for _, img_ref in imgs:
                count += 1
                try:
                    obj = img_ref.get_object()
                    w = obj.get("/Width", 0)
                    h = obj.get("/Height", 0)
                    info.append((w, h, None))
                except:
                    info.append((0,0,None))
        return count, info
    except:
        return -1, []


def get_page_size_pts(path: str) -> Tuple[int,int]:
    try:
        pdf = Pdf.open(path)
        mb = pdf.pages[0].MediaBox
        return (
            int(float(mb[2]) - float(mb[0])),
            int(float(mb[3]) - float(mb[1]))
        )
    except:
        return (0,0)


def detect_sejda_style_producer(prod: str) -> bool:
    if not prod:
        return False
    p = prod.lower().strip()
    if re.match(r"^\d+\.\d+\.\d+ ?\(", p):
        return True
    if "sejda" in p:
        return True
    return False


# -------------------------
# Main Analyzer (UNCHANGED NAME)
# -------------------------
def analyze_metadata_v2(path: str, run_ocr: bool = True) -> Dict[str, Any]:
    reasons = []

    meta = extract_pdf_metadata_pypdf(path)
    file_size = os.path.getsize(path)
    file_hash = compute_sha256(path)

    producer = (meta.get("/Producer") or "").strip()
    title = (meta.get("/Title") or "").strip()
    creation = meta.get("/CreationDate") or ""
    moddate = meta.get("/ModDate") or ""

    # -----------------------------------------
    # 1) Producer mismatch
    # -----------------------------------------
    if producer != REFERENCE_META["Producer"]:
        reasons.append("Producer does not match reference producer.")

    # 2) Sejda detection
    if detect_sejda_style_producer(producer):
        reasons.append("Producer matches Sejda-style PDF editor signature.")

    # 3) Metadata inconsistency
    if not creation and moddate:
        reasons.append("CreationDate missing but ModDate present — edited PDF.")

    # 4) Suspicious keywords
    for kw in SUSPICIOUS_KW:
        if kw in producer.lower() or kw in title.lower():
            reasons.append(f"Suspicious keyword '{kw}' detected.")

    # 5) File size anomalies
    if file_size < MIN_FILE_SIZE:
        reasons.append("File too small.")
    if file_size > MAX_FILE_SIZE:
        reasons.append("File too large — likely rasterized.")

    # -----------------------------------------
    # 6) Embedded image structure
    # -----------------------------------------
    img_count, img_info = count_images_and_ppi(path)
    expected = REFERENCE_META["ExpectedImageCount"]

    # NEW FIX: If PikePDF fails (img_count = -1), ignore this rule.
    if img_count != -1:
        if img_count != expected:
            reasons.append(f"Image count mismatch ({img_count} vs expected {expected}).")

    # -----------------------------------------
    # 7) Page size check
    # -----------------------------------------
    pw, ph = get_page_size_pts(path)
    ew, eh = REFERENCE_META["PageSizePts"]

    if abs(pw - ew) > 4 or abs(ph - eh) > 4:
        reasons.append(f"Page size mismatch ({pw}x{ph} vs {ew}x{eh}).")

    # -----------------------------------------
    # 8) Font check (patched)
    # -----------------------------------------
    fonts_found = extract_fonts_pike(path)
    expected_fonts = REFERENCE_META["ExpectedFonts"]

    if expected_fonts and fonts_found:
        missing = [
            f for f in expected_fonts
            if not any(f.lower() in ff.lower() for ff in fonts_found)
        ]
        if missing:
            reasons.append(f"Expected fonts missing: {missing} (found: {fonts_found})")

    # -----------------------------------------
    # 9) OCR DATE CHECK
    # -----------------------------------------
    from pdf2image import convert_from_path

    ocr_year = None
    metadata_year = None

    # extract metadata year
    meta_match = re.search(r"20\d{2}", creation or moddate or "")
    if meta_match:
        metadata_year = meta_match.group(0)

    # extract OCR year
    if run_ocr:
        try:
            page = convert_from_path(path, dpi=200, poppler_path=POPLER_PATH)[0]
            text = pytesseract.image_to_string(page)
            ocr_match = re.search(r"20\d{2}", text)
            if ocr_match:
                ocr_year = ocr_match.group(0)
        except:
            ocr_year = None

    # date mismatch logic
    if metadata_year and ocr_year and metadata_year != ocr_year:
        reasons.append(f"OCR year {ocr_year} does not match metadata year {metadata_year}.")

    # metadata missing but OCR year exists → suspicious (but not for Prince)
    if ocr_year and not metadata_year and producer != REFERENCE_META["Producer"]:
        reasons.append(f"OCR detected year {ocr_year}, but metadata has no date at all.")

    # metadata exists but OCR failed
    if metadata_year and not ocr_year:
        reasons.append(f"Metadata year {metadata_year} exists, but OCR found no date.")

    # -----------------------------------------
    # SCORING
    # -----------------------------------------
    score = 1.0
    heavy = sum("producer" in r.lower() for r in reasons)
    medium = sum("mismatch" in r.lower() or "missing" in r.lower() for r in reasons)
    light = len(reasons) - heavy - medium

    score -= heavy * 0.35
    score -= medium * 0.20
    score -= light * 0.05
    score = max(0.0, round(score, 3))

    suspicious = len(reasons) > 0 and score < 0.99

    return {
        "suspicious": suspicious,
        "score": score,
        "reasons": reasons,
        "metadata": meta,
        "file_size": file_size,
        "file_hash": file_hash,
        "producer": producer,
        "title": title,
        "creation_date": creation,
        "mod_date": moddate,
        "fonts_found": fonts_found,
        "image_count": img_count,
        "page_size_pts": (pw, ph),
        "ocr_year": ocr_year,
        "metadata_year": metadata_year
    }


# CLI TEST
if __name__ == "__main__":
    import sys, json
    if len(sys.argv) < 2:
        print("Usage: python metadata_viewer_v2.py <path-to-pdf>")
        exit(1)
    print(json.dumps(
        analyze_metadata_v2(sys.argv[1], run_ocr=True),
        indent=2
    ))
