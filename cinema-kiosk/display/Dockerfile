FROM debian:bookworm-slim

ENV PYTHONUNBUFFERED=1 \
    SDL_VIDEODRIVER=kmsdrm \
    SDL_AUDIODRIVER=dummy \
    IMAGE_DIR=/data/current

# python3-pygame links Debian's SDL2, which is built with KMS/DRM + GLES support.
# The mesa/gbm/drm libraries give SDL a GPU renderer on the Pi (vc4/v3d).
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pygame python3-pil \
        libdrm2 libgbm1 libegl1 libgles2 libgl1-mesa-dri \
 && rm -rf /var/lib/apt/lists/*

COPY display.py /app/display.py
WORKDIR /app
CMD ["python3", "display.py"]
