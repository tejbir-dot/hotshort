FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .

RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    build-essential \
    curl \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libatlas-base-dev \
    liblapack-dev \
    gfortran \
    libsndfile1 \
    libsndfile1-dev \
    libjack0 \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip setuptools wheel

RUN pip install --no-cache-dir --no-build-isolation -r requirements.txt

COPY . .

CMD ["python", "runpodworker.py"]
