from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from metadata_viewer_v2 import analyze_metadata_v2
import tempfile, os

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/metadata-check")
async def metadata_check(file: UploadFile = File(...)):
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    try:
        tmp.write(await file.read())
        tmp.close()
        report = analyze_metadata_v2(tmp.name, run_ocr=True)
        return report
    finally:
        os.unlink(tmp.name)
