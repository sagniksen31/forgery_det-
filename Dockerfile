# ---- Base Image ----
FROM python:3.10-slim

# ---- Install Dependencies ----
RUN apt-get update && apt-get install -y \
    poppler-utils \
    tesseract-ocr \
    tesseract-ocr-eng \
    libtesseract-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# ---- Create working directory ----
WORKDIR /app

# ---- Install Python dependencies ----
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---- Add your app ----
COPY . .

# ---- Expose port ----
EXPOSE 8000

# ---- Run FastAPI ----
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
