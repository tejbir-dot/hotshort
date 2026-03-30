FROM python:3.10

WORKDIR /app

COPY . .

RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip

# 👇 IMPORTANT FIX
RUN pip install --no-cache-dir -r requirements.txt

CMD ["python", "runpodworker.py"]
