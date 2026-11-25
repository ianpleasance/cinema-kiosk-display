# Changelog

All notable changes to this project are recorded here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/). The current version is in the [`VERSION`](cinema-kiosk/VERSION) file.

## [Unreleased]

## [1.0.0] - 2026-11-20

First release.

### Added

- **Raspberry Pi 3B+ or later**: the install guide is written for a Pi 3B+, 4 or 5 running Raspberry Pi OS
  Lite (64-bit) with Docker from its install script, and warns that the original Pi Zero, Zero W and
  Pi 1 (ARMv6) cannot run Docker. The updater image is built from Debian packages instead of pip, so it
  builds on 32-bit and 64-bit alike. The guide also sets up passwordless `sudo` for `cinema`.
- **Package layout**: the guides (`README.md`, `INSTALL.md`, `USAGE.md`, `CHANGELOG.md`) are at the top of
  the package and the application is in a `cinema-kiosk/` folder beside them.
- **Several refresh times a day**: `RUN_AT` accepts a list such as `0330,1230,1530,2030`, so
  matinee and evening shows disappear soon after they have started.
- **Archive**: images of films that have dropped off the schedule are copied to
  `archive/<date>/` instead of being lost. A `manifest.json` in each image set lists its films.
- **Sudden-drop safety check**: if a refresh finds more than `MAX_ITEM_DROP` (default 5)
  fewer films than the last good one, it is rejected, the old images stay on screen and an error
  is logged. `updater.py --once --force` overrides it.
- **Updater log file** (`logs/updater.log`, rotating, setting `LOG_FILE`), including `.env`
  warnings.
- **Slideshow video** (`VIDEO_MODE`: `none`, `plain`, `fade` or `both`): the updater can also
  make an mp4 of the slideshow in `video/`, with or without fades, using the display's timing
  settings and your static images. It is only remade when the slides or related settings change.
- **Install guide** (`INSTALL.md`) rewritten for a headless install from a blank SD card: flashing with
  Imager (hostname, a `cinema` user, Wi-Fi, SSH), base system set-up (time zone, Wi-Fi power saving off,
  1080p output, hardware watchdog, an optional swap file), a backup Wi-Fi network, Docker, and
  optional Tailscale.
- **Network shares**: the `static` and `slides` folders can be shared read/write with Samba, using the
  `cinema` user and password, so images can be added and checked from a PC or Mac.
- **User guide** (`USAGE.md`): changing settings and restarting, a reference for every setting, adding
  static images, the slides folder and archive, the video, logs and troubleshooting.
- **Rotation**: static images (such as phone photos) are shown the right way up.
- **Updater container** that on a schedule (default once a day at 03:30) reads the Empire Theatre What's On page,
  downloads each event's poster and builds the slides. It reads the schedule data embedded in the
  page, so only one page request is needed for the dates. The new image set replaces the old one
  atomically; if a run fails the previous images stay on screen and it retries after 30 minutes.
- **Info slides**: 1920x1080 images with the poster scaled to full height on the left (two thirds
  by default) and, on the right, a rating badge, the title and the showing dates, vertically
  centred. Times are aligned in a column, long titles wrap at spaces and after `.` `:` `;` `,`
  `/` `-` `_`, HTML entities in titles are decoded, and very long date lists are truncated with
  "+ N more dates".
- **Display container**: full-screen slideshow straight to HDMI (SDL KMS/DRM, no desktop or
  browser) with a crossfade, or fade through black, between slides. Optional random order.
- **Static images**: images placed in the `static/` folder are shown along with the film slides,
  before, after or spread evenly through them. The folder is re-read at every slide change.
- **Settings in one `.env` file**: schedule and refresh time, 12-hour or 24-hour times, days
  ahead limit, saving posters or info slides only, text, background and badge colours, rating
  badge on/off, poster width, text size limits, fonts (including a `fonts/` folder for your own),
  slide timing and fade style. Blank or invalid values fall back to defaults with a warning.
- **Console progress** while updating, for example `(3/43) Retrieving ...` followed by the dates
  found, and `updater.py --version` to see which version is running.
- **Docker Compose setup** for Raspberry Pi OS Lite with automatic restart after a reboot and
  log rotation so logs cannot fill the SD card. The rendered slides, logs, video and static images are
  ordinary folders next to the code (not hidden Docker volumes), and the updater runs as the `cinema` user
  (ID 1000) so the shared folders stay writable.
- **Documentation**: `README.md` and a step-by-step `INSTALL.md` for a Raspberry Pi, and an
  automated test suite that runs without a Pi or network access.
