FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    curl \
    libgl1 \
    libglib2.0-0 \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --upgrade pip setuptools wheel
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Professional-grade deployment pattern: Shell format allows environment variable expansion ($PORT)
CMD gunicorn app:app --workers 2 --threads 2 --timeout 120 --bind 0.0.0.0:${PORT:-8080}
