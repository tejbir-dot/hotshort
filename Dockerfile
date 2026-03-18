FROM python:3.10

WORKDIR /app

COPY . .

RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip
RUN pip install -r requirements.txt

CMD ["python", "runpod_worker.py"]