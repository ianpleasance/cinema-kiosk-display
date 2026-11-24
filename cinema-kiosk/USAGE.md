# Using the Foyer Kiosk

This guide is for looking after the kiosk once it's installed (see [INSTALL.md](INSTALL.md) if it isn't):
changing settings, adding your own images, reading the logs, and fixing problems.

Contents

- [How it works, in brief](#how-it-works-in-brief)
- [Logging in and where things are](#logging-in-and-where-things-are)
- [Everyday commands](#everyday-commands)
- [Changing settings and restarting](#changing-settings-and-restarting)
- [Settings reference](#settings-reference)
- [Your own images (static)](#your-own-images-static)
- [Rendered slides and the archive](#rendered-slides-and-the-archive)
- [When the slides refresh](#when-the-slides-refresh)
- [Slideshow video](#slideshow-video)
- [Your own fonts](#your-own-fonts)
- [Logs and troubleshooting](#logs-and-troubleshooting)
- [Updating the software](#updating-the-software)

## How it works, in brief

Two programs run on the Pi, each in its own Docker container:

- The **updater** reads the cinema's What's On page at the times you set (`RUN_AT`), downloads each
  film's poster and builds the slides: the original poster, and an "info" slide with the poster, the
  rating, the title and the dates and times. It writes them to the `slides` folder.
- The **display** shows the slides full screen over HDMI, fading from one to the next, and also shows
  any images you've put in the `static` folder.

The updater only switches to a new set of slides once the whole set is built, so the screen never goes
blank, and if the website is down or looks wrong the old slides stay up and it tries again later.

## Logging in and where things are

**[computer]** Log in to the Pi, then go to the project folder. All the commands below are run there:

```bash
ssh cinema@foyer-kiosk.local
cd ~/cinema-kiosk
```

| Folder or file | What it is |
|---|---|
| `.env` | **All the settings.** The one file you edit. (Hidden: `ls -a` shows it.) |
| `static/` | **Your own images**, shown along with the film slides. Shared on the network. |
| `slides/` | The slides the updater makes (`current/`) and the `archive/`. Shared on the network. |
| `video/` | The slideshow mp4, if you ask for one. |
| `logs/` | `updater.log`, the updater's log file. |
| `fonts/` | Your own font files, if you use any. |
| `docker-compose.yml` | How the two containers are put together. You rarely need to touch it. |

## Everyday commands

Run in `~/cinema-kiosk`.

| To do this | Run |
|---|---|
| See what's running | `docker compose ps` |
| Follow the logs live | `docker compose logs -f` (add `updater` or `display` for one) |
| Read the updater's log file | `tail -n 100 logs/updater.log` |
| Refresh the slides now | `docker compose exec updater python updater.py --once` |
| Refresh and accept a big drop in films | `docker compose exec updater python updater.py --once --force` |
| Apply changes made in `.env` | `docker compose up -d` |
| Restart just the screen | `docker compose restart display` |
| Restart both | `docker compose restart` |
| Stop / start | `docker compose stop` / `docker compose start` |
| Show the version | `cat VERSION` |
| List the slides on screen | `ls slides/current` |
| Restart the whole Pi | `sudo reboot` |
| Shut it down cleanly | `sudo shutdown now` |

After a power cut or reboot nothing needs doing: both containers start by themselves.

## Changing settings and restarting

1. Open the settings file:

   ```bash
   nano .env
   ```

   Change a value, then save with **Ctrl+O**, **Enter**, and leave with **Ctrl+X**.

2. Apply it:

   ```bash
   docker compose up -d
   ```

   This recreates whichever container's settings changed, which takes a few seconds. The screen goes
   blank briefly if the display restarts.

3. Some changes also need the slides redrawn, because the updater bakes the look into the images.
   Refresh them now rather than waiting for the next scheduled run:

   ```bash
   docker compose exec updater python updater.py --once
   ```

   It prints its progress as it works; the screen carries on showing the old slides until the new set is
   complete, then switches.

Which settings need the extra refresh:

| You changed... | Then do |
|---|---|
| `HOLD_SECONDS`, `FADE_SECONDS`, `FADE_MODE`, `SHUFFLE`, `STATIC_POSITION` | `up -d` only |
| `RUN_AT`, `TZ`, `RETRY_MINUTES`, `REQUEST_DELAY`, `MAX_ITEM_DROP`, `LOG_FILE` | `up -d` only; the updater then waits for the next time |
| Anything about how slides look: colours, fonts, text sizes, `POSTER_WIDTH_PERCENT`, `SHOW_RATING`, `TIME_FORMAT`, `SAVE_POSTERS`, `SCREEN_W`, `SCREEN_H` | `up -d`, then refresh |
| `BACKGROUND_COLOUR` | `up -d`, then refresh (it changes the slides and the display) |
| What's included: `DAYS_AHEAD`, `LISTING_URL` | `up -d`, then refresh |
| `VIDEO_MODE` | `up -d`; the updater checks the video when it restarts. Run a refresh to make it sooner |
| Files in `static/` | nothing; picked up at the next slide change |

**Rules for the file.** One `NAME=value` per line; **no quotes**, **no spaces around the `=`**, and
comments only on their own lines starting with `#`. Never put a `#` inside a value (it would be treated as
a comment), which is why colours are written without one: `C8102E`, not `#C8102E`. If a value is blank or
isn't valid, that setting quietly falls back to its default, and a warning appears in the log
(`Setting: ...`); check `tail logs/updater.log` after a change if something doesn't seem to take.

## Settings reference

Every setting is in `.env`, with a comment above it. "Applies" shows what's needed after changing it
(see the table above). The settings below are grouped by what they affect.

### When and what: the updater

| Setting | Default | Allowed | What it does |
|---|---|---|---|
| `TZ` | `Europe/London` | a timezone name | The timezone for run times and dates, and for deciding that a showing is in the past |
| `RUN_AT` | `03:30` | one or more 24-hour times | When the slides refresh. Separate several with commas or spaces, as `03:30` or `0330`: `RUN_AT=0330,1230,1530,2030`. Several runs a day mean a finished matinee or evening show disappears soon after |
| `MAX_ITEM_DROP` | `5` | `0` to `1000` | Safety check: a refresh with more than this many *fewer* films than the last good one is rejected and the old slides kept. `0` turns it off. See [When the slides refresh](#when-the-slides-refresh) |
| `LOG_FILE` | `/logs/updater.log` | a path, or `off` | The updater's log file, which appears as `logs/updater.log`. `off` logs to the console only |
| `LISTING_URL` | the What's On page | a web address | Where the schedule is read from |
| `DAYS_AHEAD` | `0` | `0` to `3650` | `0` shows every event on the schedule; `N` shows only today plus the next `N` days |
| `TIME_FORMAT` | `12h` | `12h` or `24h` | `12h` writes 7:30pm, `24h` writes 19:30 |
| `SAVE_POSTERS` | `1` | `1` or `0` | `1` keeps each original poster *and* the info slide (the poster shows first, then the info slide); `0` keeps only the info slides |
| `RETRY_MINUTES` | `30` | `1` or more | How long to wait before trying again after a failed refresh |
| `REQUEST_DELAY` | `0.5` | `0` or more | Seconds to pause between requests to the website, to be polite |
| `SCREEN_W`, `SCREEN_H` | `1920`, `1080` | `320`+ / `240`+ | The size of the slides the updater makes. Match your screen |

### How the slides look: the updater

| Setting | Default | Allowed | What it does |
|---|---|---|---|
| `TEXT_COLOUR` | `FFFFFF` | 6-digit hex (or 3-digit like `FC0`), no `#` | Title and dates |
| `BACKGROUND_COLOUR` | `000000` | hex | The text panel, and the edges around posters and your static images |
| `BADGE_COLOUR` | `C8102E` | hex | The rating circle |
| `BADGE_TEXT_COLOUR` | `FFFFFF` | hex | The text inside the rating circle |
| `SHOW_RATING` | `1` | `1` or `0` | `0` hides the rating circle |
| `POSTER_WIDTH_PERCENT` | `66.67` | `20` to `90` | How much of the screen's width the poster gets; the text panel gets the rest. `66.67` is two thirds |
| `TITLE_SIZE_MAX`, `TITLE_SIZE_MIN` | `88`, `40` | `20`-`300`, `12`-`300` | Title text size in pixels (on a 1080-high slide). The largest size that fits is used, shrinking towards the minimum for long titles |
| `DATE_SIZE_MAX`, `DATE_SIZE_MIN` | `56`, `30` | `12`-`200` | The same, for the dates and times |
| `FONT_BOLD`, `FONT_REG` | DejaVu Sans | a font file path | Bold is used for the title and rating, regular for the dates. See [Your own fonts](#your-own-fonts) |

Colours are written like `FFD700` (gold), `FFFFFF` (white), `000000` (black), `C8102E` (red), with no `#`.
A minimum larger than its maximum is ignored (the defaults are used) with a warning.

### The screen: the display

| Setting | Default | Allowed | What it does |
|---|---|---|---|
| `HOLD_SECONDS` | `10` | `0.5` or more | How long each slide stays on screen |
| `FADE_SECONDS` | `1.0` | `0` or more | How long each fade takes. `0` cuts straight to the next slide |
| `FADE_MODE` | `cross` | `cross` or `black` | `cross` blends one slide into the next; `black` fades out to black, then in |
| `SHUFFLE` | `0` | `1` or `0` | `1` shows the slides in random order (never the same one twice in a row); `0` follows the schedule's order |
| `STATIC_POSITION` | `after` | `after`, `before`, `spread` | Where your static images go among the film slides: after them all, before them all, or spread evenly through them |

`BACKGROUND_COLOUR` (above) is used by the display too, for the edges around your static images.

### The video (optional)

| Setting | Default | Allowed | What it does |
|---|---|---|---|
| `VIDEO_MODE` | `none` | `none`, `plain`, `fade`, `both` | Also make an mp4 of the slideshow. See [Slideshow video](#slideshow-video) |

### Advanced (not in `.env` normally)

`USER_AGENT` (how the updater identifies itself to the website), `DATA_DIR`, `STATIC_DIR` and
`VIDEO_DIR` (where things are inside the containers) can also be set in `.env`, but there's rarely a
reason to. The folders inside the containers are connected to the project's folders by
`docker-compose.yml`; changing them there as well as here is the only safe way.

## Your own images (static)

Anything you put in the `static` folder is shown along with the film slides: house rules, offers,
"coming soon", sponsors, a message of the day.

**Adding images**

- **Over the network** (easiest): open `\\foyer-kiosk\static` on Windows, or `smb://foyer-kiosk.local/static` on
  a Mac, log in as `cinema`, and drag the files in. See [INSTALL.md, step 8](INSTALL.md#8-share-the-image-folders-on-the-network).
- **From a terminal on your computer:** `scp offers.png cinema@foyer-kiosk.local:~/cinema-kiosk/static/`
- **On the Pi:** copy into `~/cinema-kiosk/static/`.

**Rules and tips**

- File types: `.jpg`, `.jpeg`, `.png`, `.webp`, `.gif`, `.bmp`. Other files are ignored, so notes can sit
  alongside. An animated GIF shows as a still (its first frame).
- Any size or shape works: the image is scaled to fit the screen, with `BACKGROUND_COLOUR` filling the
  edges. For a perfect fit make it **1920x1080** (or whatever `SCREEN_W` x `SCREEN_H` is).
- PNGs with transparency are placed on `BACKGROUND_COLOUR`. Photos taken on a phone are shown the right way up.
- **Order:** they appear in file name order (not case-sensitive), so name them `01_offers.png`,
  `02_house-rules.png` to control it. With `SHUFFLE=1` the order is random.
- **Position among the films:** `STATIC_POSITION` decides: `after` (default), `before`, or `spread` (evenly
  through the film slides).
- **No restart or refresh needed.** The folder is looked at every time the slide changes, so a new image
  appears within one slide (about `HOLD_SECONDS`), and a deleted one stops appearing. To take an image
  down, delete it, or to keep it for later, move it into a sub-folder or give it a name starting with a
  dot; files inside folders and files starting with `.` are ignored.
- If you change images over the network share while the slide is up, the display copes with a half-copied
  file by skipping it for that round.
- Static images are included in the [slideshow video](#slideshow-video) too.

## Rendered slides and the archive

The updater's slides are in `slides/` (shared on the network as `\\foyer-kiosk\slides`):

```
slides/
  current/             what the screen shows now (a link to the newest gen-... folder)
  gen-20261124-033000/ the newest set; the one before it is kept as a fallback, older ones are deleted
  archive/2026-11-24/  images of films that have left the schedule
```

- Files in `current/` are named `01_<title>_a_poster.jpg` (the original poster, if `SAVE_POSTERS=1`) and
  `01_<title>_b_info.jpg` (the info slide), then `02_...` and so on, in the website's order, so each
  poster is followed by its info slide. A `manifest.json` lists the set's films and can be ignored.
- **Taking a slide down by hand:** delete it from `current/`. It disappears from the screen straight
  away, but it comes back at the next refresh if the film is still on the schedule. There is no setting for hiding
  one film permanently; `DAYS_AHEAD` limits how far ahead films are shown.
- **The archive.** When a film is no longer on the schedule its slides are copied to
  `archive/<date>/` (the date it dropped off). The display never shows the archive, and nothing deletes
  it. It grows by a few MB per film, so clear out old months now and then, either through the
  `slides` share, or from a terminal: `rm -rf slides/archive/2026-01*`.
- Check disk space occasionally: `df -h /`.

## When the slides refresh

- **At the `RUN_AT` times** (default 03:30 each day), and **straight away** the first time, if there are
  no slides yet. After you change a look setting, run a refresh by hand (above).
- **The Pi has to be on at those times.** A refresh missed because the Pi was off waits for the next
  scheduled time.
- **If a refresh fails** (no internet, website down) the old slides stay up, and it tries again after
  `RETRY_MINUTES`.
- **The sudden-drop check.** The cinema normally has a handful of films change from one refresh to the
  next. If a refresh finds **more than `MAX_ITEM_DROP` fewer films** than the last good one (default
  5), it assumes the website is broken or has changed, throws the new set away and keeps the old one,
  and logs `update NOT applied: only 3 films ... against 21 last time`. It then waits for the next
  scheduled time rather than hammering the site. If the schedule really did shrink (a festival
  ended), accept it: `docker compose exec updater python updater.py --once --force`, or raise
  `MAX_ITEM_DROP`. `0` turns the check off. The first refresh on a fresh install is never checked.
- Films that dropped off the schedule are archived (see above), and old showings (dates and times
  already past) are removed from the slides each refresh.

## Slideshow video

Set `VIDEO_MODE` in `.env` and the updater also writes an mp4 of the slideshow to the `video/` folder:

| `VIDEO_MODE` | Result |
|---|---|
| `none` | no video (default) |
| `plain` | `slideshow.mp4`: each slide held for `HOLD_SECONDS`, with no fades. Quick to make |
| `fade` | `slideshow-fade.mp4`: with the `FADE_SECONDS` / `FADE_MODE` fades. Slower to make |
| `both` | both files |

Apply it with `docker compose up -d`. The video shows the film slides with your `static` images placed by
`STATIC_POSITION`, always in schedule order (`SHUFFLE` is ignored), at `SCREEN_W` x `SCREEN_H`, 25 frames
per second. Fetch the file from `video/` through the network (`\\foyer-kiosk\video`, if you added that share)
or with `scp cinema@foyer-kiosk.local:~/cinema-kiosk/video/slideshow.mp4 .`

- It is **only remade when it needs to be**: when the slides (their content or order), your static images,
  or the settings that affect it change. Changing `FADE_SECONDS` only remakes the fading video. Most
  refreshes change nothing, so they cost nothing.
- A video you stop asking for (by changing `VIDEO_MODE`) is **deleted**.
- Making the video takes minutes on a Pi (longer on a Zero 2 W) at low priority, so the display isn't
  disturbed; the next scheduled refresh check is delayed by that long. If a video fails to make, it's
  logged (`Video: ...`) and the slides are unaffected.

## Your own fonts

1. Copy a bold and a regular `.ttf` or `.otf` file into the `fonts` folder (for example with `scp`).
2. In `.env` set `FONT_BOLD=/fonts/MyFont-Bold.ttf` and `FONT_REG=/fonts/MyFont-Regular.ttf`. The path
   starts with `/fonts/` whatever the folder is called on the Pi, and the name is case-sensitive.
3. `docker compose up -d`, then refresh the slides.

If a font can't be loaded the updater logs a warning and uses the built-in DejaVu Sans. Only use fonts you
have a licence for.

## Logs and troubleshooting

### Reading the logs

```bash
tail -n 100 logs/updater.log                 # the updater's own log file, last 100 lines
tail -f logs/updater.log                     # follow it live (Ctrl+C to stop)
grep -E "WARNING|ERROR" logs/updater.log | tail -n 50
docker compose logs -f                       # both containers live
docker compose logs --tail 100 display       # the last 100 lines from the display
docker compose logs --since 1h updater       # the last hour
```

The log file survives rebuilds and is replaced by `updater.log.1`, `.2` ... at about 2 MB (5 old
ones are kept), so it can't fill the card. Docker also keeps the last 30 MB or so of each container's
console output. What the updater's lines mean:

| Line | Meaning |
|---|---|
| `Empire kiosk updater v1.0.0 starting (updates at 03:30 Europe/London)` | Started: the version and the times it will update |
| `Setting: ...` / `WARNING: SETTING=... is not ...` | A bad value in `.env`; the default was used instead |
| `(7/43) Retrieving <title>` then `Done: 2 dates: ...` | Progress, and the dates found for each film |
| `(7/43) Skipped <title>: <reason>` | One film failed; the rest carry on |
| `Update complete: 43 films, 86 files` | Success |
| `Archived 2 film(s) no longer on the schedule: ...` | Those films' slides were saved to the archive |
| `update NOT applied: only 3 films ... against 21 last time` | The sudden-drop check; see [When the slides refresh](#when-the-slides-refresh) |
| `update failed - keeping previous images, retrying in 30 min` | Failure; the old slides stay on screen. The lines just above say why |
| `no films found in listing - page layout may have changed` | The website changed how it publishes the schedule: the code needs updating |
| `Video: ...` | Slideshow video progress or problems |

The display's: `Empire kiosk display v1.0.0 starting`, then `Display 1920x1080 (gpu)` (the fast, preferred
mode). `GPU renderer unavailable ... using software blit` works but fades may be less smooth, and `could not
load <file>` means one image is unreadable and is skipped.

### Checking state

```bash
docker compose ps                            # status; "restarting" means it keeps crashing
docker compose ps -a                         # includes stopped containers
docker compose exec updater ls -l /data/current
docker compose config                        # the settings after .env has been applied
docker stats --no-stream                     # CPU and memory use
vcgencmd get_throttled                       # 0x0 = power and heat are fine
cat /proc/device-tree/model                  # which Pi this is
df -h /                                      # disk space
docker compose exec updater python -c "import requests; print(requests.get('https://empire-theatre.co.uk', timeout=15).status_code)"
                                             # 200 = the updater can reach the website
```

### Common problems

| Symptom | Likely cause and fix |
|---|---|
| **Screen black, `docker compose ps` shows display "Up"** | Probably no slides yet: check `tail logs/updater.log` and `ls slides/current`. If slides exist it's a display-driver problem: see the next rows |
| **Display keeps restarting, or the log mentions `kmsdrm`, `DRM`, "No available video device"** | (1) Check `/dev/dri` exists and `dtoverlay=vc4-kms-v3d` is in `/boot/firmware/config.txt`; reboot. (2) A desktop session is holding the screen: use Raspberry Pi OS **Lite**. (3) In `docker-compose.yml` uncomment `privileged: true` under `display` and run `docker compose up -d` |
| **Wrong picture size, black borders all round, or very slow** | The screen is running at 4K or an odd mode. Force 1080p ([INSTALL.md, step 4](INSTALL.md#4-set-up-the-base-system)) |
| **Slides never update; log says `update failed`** | Read the lines above it. A network error: check the Wi-Fi and the website test above. The old slides stay on screen meanwhile |
| **`update NOT applied`** | The drop check. Wait for the next run, or `--once --force` if the smaller schedule is real |
| **`no films found in listing`** | The cinema's website changed. Report it with the logs (below) |
| **Dates or times a day out, or the wrong style** | Check `TZ` and `TIME_FORMAT` in `.env`, and the Pi's clock with `timedatectl`. Then refresh |
| **Changed `.env` but the slides look the same** | The look is set when the updater runs: refresh with `docker compose exec updater python updater.py --once` |
| **Setting seems ignored** | Look for `Setting: ...` lines in `logs/updater.log`: an invalid value falls back to the default. Check there are no quotes or spaces around `=` |
| **Custom font not used** | The log shows a warning with the path. The file must be in `fonts/`, the path must start with `/fonts/`, and the name is case-sensitive |
| **Text too small or too large** | Adjust `TITLE_SIZE_MAX/MIN` and `DATE_SIZE_MAX/MIN`, then refresh |
| **A static image doesn't appear** | It must be a jpg, png, webp, gif or bmp, directly inside `static/` (not a sub-folder or starting with a dot). `ls static` on the Pi shows what it sees |
| **A deleted film is still on screen** | Slides in `slides/current` stay until the next refresh. Refresh now |
| **Fades stutter** | `vcgencmd get_throttled` (power or heat?), the display log mentioning `software blit`, and whether the screen is running at 4K. On a Zero 2 W try `FADE_MODE=black` |
| **Can't open the network share, or can't save into it** | See [INSTALL.md, step 14](INSTALL.md#14-if-something-goes-wrong-during-installation) (password, `smbd` running, folder ownership) |
| **The Pi is unreachable** | Check power and the network. If both Wi-Fi networks are out, plug in Ethernet (Pi 4/5). Then `ssh` in and check `nmcli`. If it's frozen, the watchdog should reboot it; otherwise power-cycle it |
| **Disk full** | `df -h /`, then clear the `slides/archive` and `docker system df` / `docker image prune -f` |

### Reporting a problem

When asking for help, include the output of these (in `~/cinema-kiosk`):

```bash
cat VERSION
docker compose ps
tail -n 100 logs/updater.log
docker compose logs --tail 100
cat /proc/device-tree/model; grep PRETTY_NAME /etc/os-release
ls -l /dev/dri
```

Leave out passwords and anything private.

## Updating the software

```bash
cd ~/cinema-kiosk
cat VERSION                                  # the version you have now
git pull --rebase --autostash                # your edits to .env are kept
docker compose up -d --build
docker compose exec updater python updater.py --once
```

Read the [CHANGELOG](CHANGELOG.md) first to see what's new. New settings have built-in defaults, so an old
`.env` keeps working. More detail, including going back to an earlier version, is in
[INSTALL.md, step 13](INSTALL.md#13-updating-to-a-new-version).
