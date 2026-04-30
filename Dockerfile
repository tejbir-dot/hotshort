FROM python:3.10-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_DEFAULT_TIMEOUT=100 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install runtime system dependencies needed by the Railway web app.
# nodejs is required by yt-dlp for JS-based YouTube extraction (fixes "JS runtime missing" warning).
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    nodejs \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY requirements.railway.txt .

# Install only the web dependencies needed for Railway.
RUN python -m pip install --upgrade pip setuptools wheel && \
    python -m pip install --prefer-binary --progress-bar off -r requirements.railway.txt

COPY . .

CMD ["sh", "-c", "gunicorn app:app --bind 0.0.0.0:${PORT:-8080} --workers 2 --threads 2 --timeout 120"]
