FROM debian:bookworm-slim

ENV PYTHONUNBUFFERED=1 \
    TZ=Europe/London \
    DATA_DIR=/data

# Everything comes from Debian's own packages rather than pip. That way the image builds
# the same on 32-bit and 64-bit Raspberry Pi OS (pip has no ready-made Pillow for 32-bit
# ARM and would have to compile it), and it matches the display image's base.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        python3 python-is-python3 python3-requests python3-bs4 python3-lxml python3-pil \
        fonts-dejavu-core ffmpeg tzdata ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY updater.py /app/updater.py
WORKDIR /app
CMD ["python", "updater.py"]
