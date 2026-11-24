# Empire Theatre Foyer Kiosk

A self-updating digital poster display for a cinema foyer. It runs on a Raspberry Pi, outputs
full-screen over HDMI, and shows a looping slideshow of what's on, built automatically every day
from the theatre's own website.

**Version 1.0.0** · see the [CHANGELOG](CHANGELOG.md) · [INSTALL.md](INSTALL.md) is the
step-by-step Raspberry Pi setup · [USAGE.md](USAGE.md) covers running it and every setting

![Example slide: poster on the left, rating badge, title and showing dates on the right](docs/example-slide.jpg)

*An example slide (fictional poster). The real ones use each event's own poster.*

## What it does

- **Reads the schedule** (daily, or at several times a day) from the [What's On page](https://empire-theatre.co.uk/EmpireTheatre.dll/WhatsOn):
  every film, event cinema, comedy night and so on, with its poster and all its showing dates.
- **Builds a slide for each event**: the poster scaled to full height on the left, and on the right
  a rating badge, the title and the dates and times (aligned in columns, in 12-hour or 24-hour
  style), vertically centred. Optionally the original poster is kept as a slide of its own too.
- **Shows them full screen** with a fade between slides, straight to HDMI. No desktop, browser or
  keyboard needed.
- **Mixes in your own images** (house rules, offers, sponsors...) from a `static/` folder.
- **Looks after itself**: restarts after a power cut, keeps showing the previous images if the
  website is down, and retries until it works.
- **Is configured from one file**, [`.env`](.env): colours, fonts, sizes, timings, how far ahead to
  show, and more.

## How it works

Two containers share a folder (`slides/`):

```
   empire-theatre.co.uk                 ┌───────────────────────────┐
   (What's On page)  ── at set times ─▶ │  updater                  │
                                        │  reads schedule + posters │
                                        │  draws the slides         │
                                        └─────────────┬─────────────┘
                                                      │ writes
                                              ┌───────▼───────┐
                                              │ ./slides      │
                                              └───────┬───────┘
                                                      │ reads
   ./static  (your own images) ───────────────┐       │
                                        ┌─────▼───────▼─────────────┐
                                        │  display                  │ ──▶  HDMI
                                        │  fades through the slides │
                                        └───────────────────────────┘
```

- **`updater`** (Python, Pillow) builds each new set of images in a temporary folder and switches
  to it in one step, so the display never sees a half-finished set.
- **`display`** (Python, pygame on SDL's KMS/DRM driver) re-reads the folders at every slide
  change, so new images from the updater, or files you drop into `static/`, appear on their own.

## Quick start

**You need:** a Raspberry Pi 4 or 5 running Raspberry Pi OS Lite (64-bit) with a display on HDMI,
and Docker with the Compose plugin. [INSTALL.md](INSTALL.md) walks through all of this from a blank
SD card: headless setup, a `cinema` user, two Wi-Fi networks, Docker, and network shares for the
image folders. [USAGE.md](USAGE.md) then explains running it.

```bash
git clone <your-repo-url> cinema-kiosk
cd cinema-kiosk

# 1. (optional) look through the settings and change what you like
nano .env

# 2. build both images and start everything in the background
docker compose up -d --build

# 3. watch it work; the first update starts straight away
docker compose logs -f
```

The first build takes a few minutes. The updater downloads the schedule and builds the slides
(you'll see `(1/43) Retrieving ...` lines), and the display starts showing them. Both containers
restart automatically after a reboot.

Stop everything with `docker compose down`. Your slides are ordinary files in the `slides/` folder and
survive this; delete `slides/gen-*` and `slides/current` to start from scratch (the updater then
rebuilds them on the next start).

### Trying the updater on another computer (no Pi)

The display needs the Pi's graphics device (`/dev/dri`), but the updater runs anywhere Docker does.
Handy for previewing the slides, or developing on a laptop:

```bash
docker compose up -d --build updater
docker compose logs -f updater            # wait for "Update complete"

ls slides/current                        # the finished slides
```

Then open the images in `slides/current/`. (The updater runs as user ID 1000, set by `user:` in
`docker-compose.yml`; if your own user ID differs, change that line so it can write to the folders.)

## Configuration

Everything is set in [`.env`](.env), which both containers read; [USAGE.md](USAGE.md#settings-reference) describes each setting in detail. Each setting has a comment above
it in the file. Edit it, then apply with `docker compose up -d`. Changes to how slides *look* or
which events are included need the updater to run again to take effect, so refresh straight away
with `docker compose exec updater python updater.py --once` (or wait for the next scheduled run).

| Setting | Default | What it does |
|---|---|---|
| `TZ` | `Europe/London` | Timezone for the scheduled runs and for dropping showings that have passed |
| `RUN_AT` | `03:30` | When to refresh: one or more 24-hour local times, separated by commas or spaces, as `03:30` or `0330`. E.g. `RUN_AT=0330,1230,1530,2030` so a matinee or evening show disappears soon after it starts |
| `MAX_ITEM_DROP` | `5` | Safety check: a refresh with more than this many fewer films than the last good one is rejected and the old images kept (`0` = off). See [Safety checks](#safety-checks-archive-and-the-log-file) |
| `LOG_FILE` | `/logs/updater.log` | The updater's log file (appears in `logs/` on the host); `off` = console only |
| `TIME_FORMAT` | `12h` | `12h` shows 7:30pm, `24h` shows 19:30 |
| `LISTING_URL` | the What's On page | Where the schedule is read from |
| `DAYS_AHEAD` | `0` | `0` = all events; `N` = only today plus the next N days |
| `SAVE_POSTERS` | `1` | `1` = keep each poster and its info slide; `0` = info slides only |
| `VIDEO_MODE` | `none` | Also make an mp4 of the slideshow in `video/`: `none`, `plain` (no fades), `fade` (with fades) or `both`. See [Slideshow video](#slideshow-video) |
| `RETRY_MINUTES` | `30` | Wait before retrying after a failed update |
| `REQUEST_DELAY` | `0.5` | Seconds between requests to the website |
| `SCREEN_W`, `SCREEN_H` | `1920`, `1080` | Size of the slide images |
| `TEXT_COLOUR` | `FFFFFF` | Title, dates and divider. Colours are 6-digit hex **without** a `#` |
| `BACKGROUND_COLOUR` | `000000` | Text panel and edges around posters and static images |
| `BADGE_COLOUR` | `C8102E` | Rating circle |
| `BADGE_TEXT_COLOUR` | `FFFFFF` | Text inside the rating circle |
| `SHOW_RATING` | `1` | `0` hides the rating badge |
| `POSTER_WIDTH_PERCENT` | `66.67` | Poster area as a percentage of the width (20 to 90) |
| `TITLE_SIZE_MAX`, `TITLE_SIZE_MIN` | `88`, `40` | Title text size limits in pixels |
| `DATE_SIZE_MAX`, `DATE_SIZE_MIN` | `56`, `30` | Dates text size limits in pixels |
| `FONT_BOLD`, `FONT_REG` | DejaVu Sans | Font files for the title and the dates |
| `HOLD_SECONDS` | `10` | Seconds each slide stays on screen |
| `FADE_SECONDS` | `1.0` | Seconds each fade takes |
| `FADE_MODE` | `cross` | `cross` = crossfade; `black` = fade out to black, then in |
| `SHUFFLE` | `0` | `1` = random order |
| `STATIC_POSITION` | `after` | Where your own images go: `after`, `before` or `spread` |

Write settings as `NAME=value` on one line, with no quotes or spaces around `=` and comments on their
own lines. A blank or invalid value falls back to its default and the container log shows a
warning. Advanced settings not listed in `.env` (`DATA_DIR`, `IMAGE_DIR`, `STATIC_DIR`,
`USER_AGENT`) can be added to it the same way.

### Your own images

Put images (jpg, png, webp, gif, bmp) in [`static/`](static) and the display shows them along with
the film slides. Any size works; they are scaled to fit with edges in the background colour
(1920x1080 fills the screen). They play in file name order, so `01_...`, `02_...` controls the
order, and `STATIC_POSITION` sets where they go among the film slides. No restart is needed.

### Your own fonts

Copy a bold and a regular `.ttf` or `.otf` file into [`fonts/`](fonts), then set
`FONT_BOLD=/fonts/MyFont-Bold.ttf` and `FONT_REG=/fonts/MyFont-Regular.ttf` in `.env`. If a font
can't be loaded, the updater logs a warning and uses the built-in DejaVu Sans.

## Everyday commands

Run these in the project folder.

| To do this | Run |
|---|---|
| See what's running | `docker compose ps` |
| Follow the logs | `docker compose logs -f` (add `updater` or `display` for one container) |
| Refresh the slides now | `docker compose exec updater python updater.py --once` |
| Accept a big drop in the number of films | `docker compose exec updater python updater.py --once --force` |
| Read the updater's log file | `tail -n 100 logs/updater.log` |
| Make or update the video now | `docker compose exec updater python updater.py --once` (after setting `VIDEO_MODE`) |
| See the archived images | `docker compose exec updater ls /data/archive` |
| Apply `.env` changes | `docker compose up -d` |
| Restart the display | `docker compose restart display` |
| Apply new code after `git pull` | `docker compose up -d --build` |
| List the current slides | `docker compose exec updater ls /data/current` |
| Show the running version | `docker compose exec updater python updater.py --version` |

Troubleshooting and logging are covered in [USAGE.md](USAGE.md#logs-and-troubleshooting), and Pi setup in [INSTALL.md](INSTALL.md).

## Project layout

```
.
├── README.md             this file
├── INSTALL.md            step-by-step Raspberry Pi installation
├── USAGE.md              running it: every setting, your own images, troubleshooting
├── CHANGELOG.md          what changed in each version
├── VERSION               the current version number
├── docker-compose.yml    the two services, folders and log rotation
├── .env                  all settings
├── static/               your own images (shown along with the film slides)
├── slides/               the rendered slides and the archive (not in git)
├── fonts/                your own fonts (optional)
├── logs/                 updater.log appears here (not in git)
├── video/                the optional slideshow mp4 appears here (not in git)
├── updater/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── updater.py        reads the schedule, draws the slides
├── display/
│   ├── Dockerfile
│   └── display.py        full-screen slideshow with fades
├── tests/                automated tests (no Pi or network needed)
└── docs/                 images used in this README
```

The slides are written to the `slides/` folder as `01_<title>_a_poster.jpg` and
`01_<title>_b_info.jpg`, `02_...` and so on, in schedule order, so each poster is followed by its
info slide. A `current` link always points at the newest complete set, and `manifest.json` in each
set lists the films it holds.

### Slideshow video

Set `VIDEO_MODE` in `.env` and the updater also writes an mp4 of the slideshow to the `video/`
folder: `plain` gives `slideshow.mp4` (each slide held for `HOLD_SECONDS`), `fade` gives
`slideshow-fade.mp4` (with the `FADE_SECONDS` / `FADE_MODE` fades), `both` gives both, and `none`
(the default) makes no video. It shows the film slides with your `static/` images placed
by `STATIC_POSITION`, always in schedule order (`SHUFFLE` is ignored).

A video is only remade when its slides (their content or order) or the settings that affect it
changed, so the frequent refreshes cost nothing most of the time. Changing `FADE_SECONDS` only
remakes the fading one. A video you stop asking for is deleted. Encoding runs at low priority and
is slow on a Pi (minutes, longer on a Zero 2 W), but it never delays the display and a failure
to make a video is logged without affecting the slides.

### Safety checks, archive and the log file

- **Several refreshes a day.** `RUN_AT` takes a list of times, so a film whose last showing has
  passed drops off the screen at the next refresh rather than the next morning.
- **Archive.** When a film is no longer on the schedule its images are copied to
  `archive/<date>/` in `slides/` (the display never shows them). Nothing deletes the archive:
  see [USAGE.md](USAGE.md#rendered-slides-and-the-archive).
- **Sudden-drop check.** If a refresh finds more than `MAX_ITEM_DROP` fewer films than the last
  good one (the site was down, or changed), the new set is thrown away, the old images stay on
  screen and an error is logged. It is retried at the next scheduled time. If the drop is real,
  accept it with `--once --force` (above). The first run on an empty install is never checked.
- **Log file.** The updater writes `logs/updater.log` (rotating, about 2 MB x 6 at most) as well as to
  the console, including any problems found in `.env`.

## Development

The tests need no Pi, Docker or internet access:

```bash
pip install -r tests/requirements.txt
for t in tests/test_*.py; do python3 "$t" || break; done
```

They cover the page parsing, slide drawing (layout, colours, wrapping, ratings), the update cycle
(including a failed run leaving the old images in place), the display's playlist logic, the
settings and `.env` file, and that the version numbers agree. What they can't check is the
display on real Pi hardware, so test that on a Pi after any change to `display/`.

### Releasing a new version

The project uses [Semantic Versioning](https://semver.org/). To release:

1. Set the new number in `VERSION`.
2. Set the same number in `__version__` at the top of `updater/updater.py` and `display/display.py`,
   and in the **Version** line at the top of this README.
3. In `CHANGELOG.md`, move the entries under `[Unreleased]` into a new `## [x.y.z] - YYYY-MM-DD`
   section.
4. Run the tests: `tests/test_version.py` fails if any of these disagree.
5. Commit and tag: `git tag vX.Y.Z`.

## If the website changes

The What's On page draws its event cards with JavaScript, from a block of JSON embedded in the
page (`var Events = {"Events":[ ... ]}`) holding each event's title, poster address and showings.
The updater reads that block (`parse_listing` in `updater/updater.py`), so it doesn't depend on
the page's visual layout. If the structure ever changes, the update fails with a clear message in
the log and the previous slides stay on screen until it is fixed.

The updater makes one request for the schedule plus one per poster, once a day, with a short
pause between requests.
