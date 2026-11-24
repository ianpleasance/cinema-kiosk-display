FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    TZ=Europe/London \
    DATA_DIR=/data

RUN apt-get update \
 && apt-get install -y --no-install-recommends fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY updater.py /app/updater.py
WORKDIR /app
CMD ["python", "updater.py"]
