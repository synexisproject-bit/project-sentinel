FROM python:3.11-slim

# Install uncompress (needed for .Z IONEX files)
RUN apt-get update && apt-get install -y ncompress && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements_h3.txt .
RUN pip install --no-cache-dir -r requirements_h3.txt

COPY h3_01_backfill_regional_tec.py .
COPY h3_cloudrun_main.py .

CMD ["python", "h3_cloudrun_main.py"]
