# Empire Theatre foyer kiosk

Two containers on a Raspberry Pi, sharing one volume:

| Container | What it does |
|-----------|--------------|
| `updater` | Daily (03:30 by default) reads the What's On page, downloads each poster, reads the showing dates from each film's page, and writes two files per film: the original poster and a 1920x1080 info slide (poster scaled to full height in the left two thirds, black panel with title and dates in white on the right third). The new set replaces the old one atomically; if anything fails the old set stays on screen. |
| `display` | Full-screen slideshow straight to HDMI (SDL/KMS-DRM, no desktop or browser). Shows each image for 10 s with a 1 s crossfade, re-reading the folder at every slide so new sets appear automatically. |

Files are named `01_<title>_a_poster.jpg`, `01_<title>_b_info.jpg`, `02_...` in listing (date) order, so each film's poster is followed by its info slide.

## Install on the Pi

1. Use **Raspberry Pi OS Lite (64-bit)** (no desktop running, so the display container can own the screen). In `/boot/firmware/config.txt` make sure `dtoverlay=vc4-kms-v3d` is present (it is by default).
2. Install Docker: `curl -fsSL https://get.docker.com | sh && sudo usermod -aG docker $USER`, then log out and in.
3. Copy this folder to the Pi, then:
   ```
   docker compose up -d --build
   docker compose logs -f
   ```
   The updater runs straight away if there are no images yet (watch the logs), then daily. Both containers restart automatically after a reboot.

## Settings (docker-compose.yml)

`TIME_FORMAT` (`12h` = 7:30pm, the default, or `24h` = 19:30), `RUN_AT`, `HOLD_SECONDS`, `FADE_SECONDS`, `FADE_MODE` (`cross` or `black`), `SHUFFLE=1`, `LISTING_URL`, `SCREEN_W`/`SCREEN_H` (slide size, default 1920x1080).

## Useful commands

- Refresh now: `docker compose exec updater python updater.py --once`
- Look at the images: `docker compose exec updater ls /data/current`
- Restart the display: `docker compose restart display`

## If the screen stays black

Check `docker compose logs display`. If SDL can't become DRM master or can't find a device, uncomment `privileged: true` in the compose file. On a Pi with more than one display device the wrong `/dev/dri/cardN` may be chosen; the log shows which.

## If the website changes

The What's On page draws its film cards with JavaScript from a JSON block in the page (`var Events = {"Events":[...]}`), holding each event's title, poster URL (`ImageURL`) and showings (`Performances`). The updater reads that block (`parse_listing` in `updater/updater.py`). If the page changes, the run fails and the log says so, and the old images keep displaying.

## Tests (no Pi needed)

`python3 tests/test_updater.py && python3 tests/test_display.py && python3 tests/test_e2e.py`
