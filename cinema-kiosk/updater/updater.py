#!/usr/bin/env python3
"""Empire Theatre kiosk updater.

At each time in RUN_AT (and on start-up if there is nothing to show yet) this:
  1. reads the What's On listing,
  2. for each film downloads the poster and reads the showing dates from the
     film's own page,
  3. saves a 1920x1080 "info" slide (and, if SAVE_POSTERS is on, the original poster) (poster scaled to
     full height in the left two thirds, black panel with the title and show
     dates in white on the right third),
  4. atomically switches the display over to the new set of images.

Output layout (DATA_DIR is a volume shared with the display container):
    DATA_DIR/gen-<timestamp>/   a complete set of images
    DATA_DIR/current            symlink -> the newest gen-* directory
    DATA_DIR/archive/<date>/    images of films that have dropped off the schedule
The old generation is only deleted after `current` points at the new one, and
nothing is switched if the scrape fails, so the screen never goes blank.
"""
import argparse
import hashlib
import io
import json
import logging
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta
from html import unescape
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont, ImageOps

__version__ = "1.0.0"          # keep in step with the VERSION file (a test checks this)

# ----------------------------------------------------------------- settings
STARTUP_WARNINGS = []     # settings problems found at import; replayed into the log file by main()


def warn(message):
    STARTUP_WARNINGS.append(message)
    print(f"WARNING: {message}", file=sys.stderr)


def env(name, default):
    """Setting from the environment (.env file); blank or missing falls back to the default."""
    value = os.environ.get(name, "").strip().strip("\"'").strip()   # tolerate quotes / CRLF
    return value if value else default


def env_bool(name, default):
    return env(name, "1" if default else "0").lower() in ("1", "true", "yes", "on")


def env_number(name, default, lo=None, hi=None):
    """Number setting (int if `default` is an int, else float), checked against lo..hi.
    Missing, blank, not a number or out of range -> the default, with a warning."""
    raw = env(name, "")
    if not raw:
        return default
    try:
        value = float(raw)
        if isinstance(default, int):
            value = int(value)
    except ValueError:
        warn(f"{name}={raw!r} is not a number - using {default}")
        return default
    if (lo is not None and value < lo) or (hi is not None and value > hi):
        warn(f"{name}={raw!r} is outside {lo}..{hi} - using {default}")
        return default
    return value


def env_colour(name, default_hex):
    """Colour setting as hex (FFFFFF or FFF; a leading # is tolerated) -> (r, g, b)."""
    raw = env(name, default_hex).lstrip("#")
    if re.fullmatch(r"[0-9a-fA-F]{3}", raw):
        raw = "".join(c * 2 for c in raw)
    if not re.fullmatch(r"[0-9a-fA-F]{6}", raw):
        warn(f"{name}={raw!r} is not a hex colour like FFFFFF - using {default_hex}")
        raw = default_hex
    return tuple(int(raw[i:i + 2], 16) for i in (0, 2, 4))


def env_font(name, default_path):
    """Font file setting; if it can't be loaded fall back to the bundled DejaVu font."""
    path = env(name, default_path)
    try:
        ImageFont.truetype(path, 20)
        return path
    except OSError:
        warn(f"{name}={path!r} could not be loaded as a font - using {default_path}")
        return default_path


SAVE_POSTERS = env_bool("SAVE_POSTERS", True)   # True: poster + info slide per film. False: info slide only
TIME_FORMAT = env("TIME_FORMAT", "12h").lower()   # "12h" -> 7:30pm   "24h" -> 19:30
if TIME_FORMAT not in ("12h", "24h"):
    warn(f"TIME_FORMAT={TIME_FORMAT!r} is not 12h or 24h - using 12h")
    TIME_FORMAT = "12h"
LISTING_URL = env(
    "LISTING_URL", "https://empire-theatre.co.uk/EmpireTheatre.dll/WhatsOn")
DAYS_AHEAD = env_number("DAYS_AHEAD", 0, 0, 3650)   # 0 = all events; N = today + the next N days
DATA_DIR = env("DATA_DIR", "/data")
TZ = ZoneInfo(env("TZ", "Europe/London"))


def parse_run_times(raw):
    """'0330 12:30,3:30' -> sorted unique [(3, 30), (12, 30)]. Bad entries are skipped with a warning."""
    times = set()
    for token in re.split(r"[\s,;]+", raw.strip()):
        if not token:
            continue
        m = re.fullmatch(r"(\d{1,2}):(\d{2})", token) or re.fullmatch(r"(\d{1,2})(\d{2})", token)
        if m and int(m.group(1)) <= 23 and int(m.group(2)) <= 59:
            times.add((int(m.group(1)), int(m.group(2))))
        else:
            warn(f"RUN_AT entry {token!r} is not a time like 03:30 or 0330 - ignoring it")
    return sorted(times)


RUN_TIMES = parse_run_times(env("RUN_AT", "03:30")) or [(3, 30)]    # local times, any number
RUN_AT = ",".join(f"{h:02d}:{m:02d}" for h, m in RUN_TIMES)         # normalised, for the log
RETRY_MINUTES = env_number("RETRY_MINUTES", 30, 1)
SCREEN_W = env_number("SCREEN_W", 1920, 320)
SCREEN_H = env_number("SCREEN_H", 1080, 240)
REQUEST_DELAY = env_number("REQUEST_DELAY", 0.5, 0)
USER_AGENT = env(
    "USER_AGENT", "EmpireKiosk/1.0 (cinema foyer display; daily refresh)")
KEEP_GENERATIONS = 1                                   # old sets kept besides current
# Safety check: if a run finds MORE than this many fewer films than the last good run,
# assume the scrape went wrong and keep the old images. 0 turns the check off.
MAX_ITEM_DROP = env_number("MAX_ITEM_DROP", 5, 0, 1000)
LOG_FILE = env("LOG_FILE", "/logs/updater.log")        # "off" = console only

# ---- optional slideshow video (needs ffmpeg, which the updater image includes)
VIDEO_MODE = env("VIDEO_MODE", "none").lower()         # none | plain | fade | both
if VIDEO_MODE not in ("none", "plain", "fade", "both"):
    warn(f"VIDEO_MODE={VIDEO_MODE!r} is not none/plain/fade/both - using none")
    VIDEO_MODE = "none"
VIDEO_DIR = env("VIDEO_DIR", "/video")                 # mounted from ./video
VIDEO_FPS = 25
# The video follows the display's own settings (the same .env is shared):
HOLD_SECONDS = env_number("HOLD_SECONDS", 10.0, 0.5)
FADE_SECONDS = env_number("FADE_SECONDS", 1.0, 0.0)
FADE_MODE = env("FADE_MODE", "cross").lower()          # cross | black
if FADE_MODE not in ("cross", "black"):
    warn(f"FADE_MODE={FADE_MODE!r} is not cross or black - using cross")
    FADE_MODE = "cross"
STATIC_DIR = env("STATIC_DIR", "/static")              # your own images, mounted from ./static
STATIC_POSITION = env("STATIC_POSITION", "after").lower()
if STATIC_POSITION not in ("after", "before", "spread"):
    warn(f"STATIC_POSITION={STATIC_POSITION!r} is not after/before/spread - using after")
    STATIC_POSITION = "after"

# ---- how the slides look
FONT_BOLD = env_font("FONT_BOLD", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
FONT_REG = env_font("FONT_REG", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
TEXT_COLOUR = env_colour("TEXT_COLOUR", "FFFFFF")
BACKGROUND_COLOUR = env_colour("BACKGROUND_COLOUR", "000000")
BADGE_COLOUR = env_colour("BADGE_COLOUR", "C8102E")
BADGE_TEXT_COLOUR = env_colour("BADGE_TEXT_COLOUR", "FFFFFF")
SHOW_RATING = env_bool("SHOW_RATING", True)
POSTER_WIDTH_PERCENT = env_number("POSTER_WIDTH_PERCENT", 66.67, 20, 90)
TITLE_SIZE_MAX = env_number("TITLE_SIZE_MAX", 88, 20, 300)
TITLE_SIZE_MIN = env_number("TITLE_SIZE_MIN", 40, 12, 300)
DATE_SIZE_MAX = env_number("DATE_SIZE_MAX", 56, 12, 200)
DATE_SIZE_MIN = env_number("DATE_SIZE_MIN", 30, 12, 200)
if TITLE_SIZE_MIN > TITLE_SIZE_MAX:
    warn("TITLE_SIZE_MIN is bigger than TITLE_SIZE_MAX - using 40 and 88")
    TITLE_SIZE_MIN, TITLE_SIZE_MAX = 40, 88
if DATE_SIZE_MIN > DATE_SIZE_MAX:
    warn("DATE_SIZE_MIN is bigger than DATE_SIZE_MAX - using 30 and 56")
    DATE_SIZE_MIN, DATE_SIZE_MAX = 30, 56

log = logging.getLogger("updater")


# ------------------------------------------------------------------ scraping
class Film:
    def __init__(self, film_id, title, image_url, detail_url, rating=""):
        self.rating = rating                # e.g. "15", "PG", "12A" (may be empty)
        self.id = film_id
        self.title = title
        self.image_url = image_url
        self.detail_url = detail_url
        self.showings = []        # list of (date_text, [time_text, ...])

    def __repr__(self):
        return f"Film({self.id}, {self.title!r}, {len(self.showings)} dates)"


def parse_listing(html, base_url=LISTING_URL, today=None, days_ahead=None):
    """Return a list of Film from the What's On page HTML.

    The page draws its film cards with JavaScript from a JSON blob embedded in an
    inline script (`var Events = {"Events":[...]}`), so that is what we read: it
    already holds the title, poster URL and every showing for each event.
    """
    m = re.search(r"var\s+Events\s*=\s*", html)
    if not m:
        return []
    try:
        data, _ = json.JSONDecoder().raw_decode(html, m.end())
    except ValueError as e:
        raise RuntimeError(f"could not read the embedded Events data: {e}")
    events = data.get("Events", []) if isinstance(data, dict) else data
    today = today or datetime.now(TZ).strftime("%Y-%m-%d")
    days_ahead = DAYS_AHEAD if days_ahead is None else days_ahead
    last = None                                   # last day to show (inclusive); None = no limit
    if days_ahead > 0:
        last = (datetime.strptime(today, "%Y-%m-%d") + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

    films, seen, out_of_window = [], set(), 0
    for ev in events:
        film_id = str(ev.get("ID", ""))
        title = clean_text(ev.get("Title", ""))
        image = ev.get("ImageURL")
        if not (film_id and title and image) or film_id in seen:
            if film_id and title and not image:
                log.warning("no poster image for %s - skipped", title)
            continue
        seen.add(film_id)
        detail = urljoin(base_url, ev.get("URL") or f"?f={film_id}")
        film = Film(film_id, title, urljoin(base_url, image), detail,
                    parse_rating(ev.get("Rating")))
        film.showings = group_performances(ev.get("Performances") or [], today, last)
        if ev.get("Performances") and not film.showings:
            out_of_window += 1                    # has showings, but none today onwards / within the window
            continue
        films.append(film)
    if out_of_window:
        log.info("Skipped %d events with no showings %s", out_of_window,
                 f"in the next {days_ahead} days" if last else "from today")
    return films


def clean_text(text):
    """Collapse whitespace and decode HTML entities (&amp; &#39; ... even double-encoded)."""
    text = str(text or "")
    for _ in range(3):                      # handles "&amp;amp;" style double encoding
        decoded = unescape(text)
        if decoded == text:
            break
        text = decoded
    return " ".join(text.split())


def parse_rating(rating_html):
    """'<img class="film-rating" src=".../bbfc/lrg/15.png" alt="BBFC Rating: (15)">' -> '15'."""
    if not rating_html:
        return ""
    m = re.search(r'alt="[^"]*\(([^)]+)\)', rating_html)
    if not m:
        m = re.search(r"/([A-Za-z0-9]+)\.(?:png|gif|jpe?g)", rating_html)
    text = clean_text(m.group(1)).upper() if m else ""
    return text if 0 < len(text) <= 4 else ""        # "TBC"/"Exempt"-style text is skipped


def format_times(text):
    """Rewrite any HH:MM in `text` per TIME_FORMAT ("12h": 19:30 -> 7:30pm, 00:15 -> 12:15am).
    Anything else in the text (e.g. a note after the time) is left alone."""
    if TIME_FORMAT != "12h":
        return text

    def to_12h(m):
        h, minute = int(m.group(1)), m.group(2)
        if h > 23:
            return m.group(0)
        suffix = "pm" if h >= 12 else "am"
        return f"{h % 12 or 12}:{minute}{suffix}"

    return re.sub(r"\b(\d{1,2}):(\d{2})\b", to_12h, text)


def group_performances(performances, today, last=None):
    """[(ReadableDate, [times])] in date order, one entry per day.
    Days before `today` are dropped, and days after `last` (if given)."""
    perfs = sorted((p for p in performances
                    if str(p.get("StartDate", "")) >= today
                    and (last is None or str(p.get("StartDate", "")) <= last)),
                   key=lambda p: (p.get("StartDate", ""), p.get("StartTime", "")))
    days, order = {}, []
    for p in perfs:
        key = p.get("StartDate")
        if key not in days:
            days[key] = (clean_text(p.get("ReadableDate")) or key, [])
            order.append(key)
        t = format_times(clean_text(p.get("StartTimeAndNotes") or p.get("StartTime") or ""))
        if t:
            days[key][1].append(t)
    return [days[k] for k in order]


def parse_showings(html):
    """Return [(date_text, [times])] from a film's own page."""
    soup = BeautifulSoup(html, "lxml")
    # The page contains the performances block twice (desktop + mobile); use the first.
    block = soup.select_one(".programme-performances ul.performances") \
        or soup.select_one("ul.performances")
    showings = []
    if not block:
        return showings
    for li in block.select("li.performance"):
        date_el = li.select_one(".date")
        times = [format_times(" ".join(t.get_text().split())) for t in li.select(".perf-time")]
        if date_el and times:
            showings.append((" ".join(date_el.get_text().split()), times))
    return showings


def describe_showings(showings):
    """'2 dates: Sat 21 Nov 7:30pm; Wed 25 Nov 2:30pm' (singular for 1, 'no dates' for 0)."""
    n = len(showings)
    if n == 0:
        return "no dates"
    listing = "; ".join(f"{d} {', '.join(t)}" for d, t in showings)
    return f"{n} date{'' if n == 1 else 's'}: {listing}"


def make_session():
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    return s


def fetch(session, url, **kw):
    r = session.get(url, timeout=30, **kw)
    r.raise_for_status()
    return r


# ----------------------------------------------------------------- rendering
def _font(path, size):
    return ImageFont.truetype(path, size)


BREAK_AFTER = r"[.:;,/\-_]"


def _pieces(word):
    """Split a word after . : ; , / - _ so a long word can wrap there if it has to."""
    return re.split(rf"(?<={BREAK_AFTER})(?=\S)", word)


def _wrap(draw, text, font, max_w, report=None, soft=True):
    """Greedy word wrap. Spaces are normal break points; punctuation like '.' and ':'
    inside a word is used as a break point only when the word wouldn't fit otherwise.
    A piece still too wide is split by character as a last resort (report['hard']=True)."""
    lines, cur = [], ""

    def width(t):
        return draw.textlength(t, font=font)

    for word in text.split():
        for i, piece in enumerate(_pieces(word) if soft else [word]):
            sep = "" if i > 0 else (" " if cur else "")
            if not cur or width(cur + sep + piece) <= max_w:
                cur = cur + sep + piece
            else:
                lines.append(cur)
                cur = piece
            while width(cur) > max_w and len(cur) > 1:      # last resort: split by character
                if report is not None:
                    report["hard"] = True
                n = len(cur)
                while n > 1 and width(cur[:n]) > max_w:
                    n -= 1
                lines.append(cur[:n])
                cur = cur[n:]
    if cur:
        lines.append(cur)
    return lines


def _sizes(hi, lo):
    """Font sizes to try, largest first in steps of 2, always ending on the minimum."""
    return list(range(hi, lo, -2)) + [lo]


def _fit_dates(draw, showings, size, max_w):
    """Lay the showings out as two columns: dates, then times lined up beneath each other.

    Returns (font, rows, col_x, wrapped) with rows = [(date, [time lines])].
    Times wrap inside their own column only if they have to (wrapped=True)."""
    font = _font(FONT_REG, size)
    rows = [(d, ", ".join(t)) for d, t in showings]
    if not rows:
        return font, [("Dates to be announced", [])], 0, False
    date_w = max(draw.textlength(d, font=font) for d, _ in rows)
    col_x = int(date_w + size * 0.9)
    time_w = max(1, max_w - col_x)
    out, wrapped = [], False
    for d, times in rows:
        lines = _wrap(draw, times, font, time_w, soft=False) or [""]   # times wrap at spaces only
        wrapped = wrapped or len(lines) > 1
        out.append((d, lines))
    return font, out, col_x, wrapped


def _badge_font(draw, text, diameter):
    for size in range(60, 19, -2):
        f = _font(FONT_BOLD, size)
        if draw.textlength(text, font=f) <= diameter * 0.66:
            return f
    return _font(FONT_BOLD, 20)


def render_info_panel(width, height, title, showings, rating=""):
    """Black panel: rating badge, title, divider and a two-column date/time table,
    all in white, auto-sized to fit and centred vertically."""
    panel = Image.new("RGB", (width, height), BACKGROUND_COLOUR)
    draw = ImageDraw.Draw(panel)
    pad, gap = 40, 36
    max_w = width - 2 * pad
    avail_h = height - 2 * pad
    badge_d = 104
    badge_h = (badge_d + 30) if rating else 0

    for title_size in _sizes(TITLE_SIZE_MAX, TITLE_SIZE_MIN):
        tf = _font(FONT_BOLD, title_size)
        rep = {}
        t_lines = _wrap(draw, title, tf, max_w, rep)
        if (len(t_lines) > 4 or rep.get("hard")) and title_size > TITLE_SIZE_MIN:
            continue
        t_h = len(t_lines) * int(title_size * 1.2)
        for date_size in _sizes(DATE_SIZE_MAX, DATE_SIZE_MIN):
            df, rows, col_x, wrapped = _fit_dates(draw, showings, date_size, max_w)
            if wrapped and date_size > DATE_SIZE_MIN:
                continue                              # prefer one line per showing
            d_h = sum(max(1, len(l)) for _, l in rows) * int(date_size * 1.45)
            if badge_h + t_h + gap + d_h <= avail_h:
                return _draw_panel(panel, draw, pad, rating, badge_d, tf, t_lines, title_size,
                                   df, rows, col_x, date_size, gap)

    # Lots of showings: fixed modest sizes, truncate with "+ N more dates".
    title_size, date_size = min(TITLE_SIZE_MAX, TITLE_SIZE_MIN + 4), DATE_SIZE_MIN
    tf = _font(FONT_BOLD, title_size)
    t_lines = _wrap(draw, title, tf, max_w)
    df, rows, col_x, _ = _fit_dates(draw, showings, date_size, max_w)
    room = avail_h - badge_h - len(t_lines) * int(title_size * 1.2) - gap
    step = int(date_size * 1.45)
    keep, used = [], 0
    for r in rows:
        h = max(1, len(r[1])) * step
        if used + h > room - step:                    # leave a row for the "+ N more" note
            break
        keep.append(r)
        used += h
    keep = keep or rows[:1]
    if len(keep) < len(rows):
        keep.append((f"+ {len(rows) - len(keep)} more dates", []))
    return _draw_panel(panel, draw, pad, rating, badge_d, tf, t_lines, title_size,
                       df, keep, col_x, date_size, gap)


def _draw_panel(panel, draw, pad, rating, badge_d, tf, t_lines, title_size,
                df, rows, col_x, date_size, gap):
    t_step, d_step = int(title_size * 1.2), int(date_size * 1.45)
    badge_h = (badge_d + 30) if rating else 0
    d_h = sum(max(1, len(l)) for _, l in rows) * d_step
    block_h = badge_h + len(t_lines) * t_step + gap + d_h
    y = max(pad, (panel.height - block_h) // 2)

    if rating:                                        # white text in a red circle
        draw.ellipse([pad, y, pad + badge_d, y + badge_d], fill=BADGE_COLOUR)
        bf = _badge_font(draw, rating, badge_d)
        draw.text((pad + badge_d / 2, y + badge_d / 2), rating, font=bf, fill=BADGE_TEXT_COLOUR, anchor="mm")
        y += badge_h

    for line in t_lines:
        draw.text((pad, y), line, font=tf, fill=TEXT_COLOUR)
        y += t_step
    y += gap
    draw.line([(pad, y - gap // 2), (pad + 120, y - gap // 2)], fill=TEXT_COLOUR, width=3)
    for date, time_lines in rows:
        draw.text((pad, y), date, font=df, fill=TEXT_COLOUR)
        for i, line in enumerate(time_lines):
            draw.text((pad + col_x, y + i * d_step), line, font=df, fill=TEXT_COLOUR)
        y += max(1, len(time_lines)) * d_step
    return panel


def _to_rgb_on_background(img):
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, BACKGROUND_COLOUR)
        bg.paste(img, mask=img.split()[-1])
        return bg
    return img.convert("RGB")


def compose_slide(poster_bytes, title, showings, rating="", w=SCREEN_W, h=SCREEN_H):
    """Slide: poster on the left (POSTER_WIDTH_PERCENT of the width, full height, background-
    coloured edges), title / rating / dates on the right."""
    left_w = round(w * POSTER_WIDTH_PERCENT / 100)
    poster = _to_rgb_on_background(Image.open(io.BytesIO(poster_bytes)))
    scale = min(left_w / poster.width, h / poster.height)   # full height unless too wide
    new_size = (max(1, round(poster.width * scale)), max(1, round(poster.height * scale)))
    poster = poster.resize(new_size, Image.LANCZOS)
    canvas = Image.new("RGB", (w, h), BACKGROUND_COLOUR)
    canvas.paste(poster, ((left_w - new_size[0]) // 2, (h - new_size[1]) // 2))
    canvas.paste(render_info_panel(w - left_w, h, title, showings, rating if SHOW_RATING else ""), (left_w, 0))
    return canvas


def fit_to_screen(poster_bytes, w=SCREEN_W, h=SCREEN_H):
    """Not used for saving (originals are saved untouched); handy for tests."""
    img = _to_rgb_on_background(Image.open(io.BytesIO(poster_bytes)))
    scale = min(w / img.width, h / img.height)
    return img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)


# ------------------------------------------------------------------ pipeline
def slugify(text):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:50] or "film"


def image_ext(url, content_type):
    ext = os.path.splitext(url.split("?")[0])[1].lower()
    if ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        return ext
    return mimetypes.guess_extension((content_type or "").split(";")[0]) or ".jpg"


class SuspiciousUpdate(RuntimeError):
    """The new image set looks wrong (far fewer films than before); the old one is kept."""


def film_key(film):
    return {"id": film.id, "slug": slugify(film.title), "title": film.title}


def read_manifest(gen_dir):
    """The films in an image set: [{"id", "slug", "title", "files": [...]}].
    Uses manifest.json, or works it out from the file names if there isn't one."""
    try:
        with open(os.path.join(gen_dir, "manifest.json"), encoding="utf-8") as f:
            return json.load(f)["films"]
    except (OSError, ValueError, KeyError):
        pass
    films = {}
    try:
        names = sorted(os.listdir(gen_dir))
    except OSError:
        return []
    for name in names:
        m = re.match(r"\d+_(.+?)_[ab]_(?:poster|info)\.\w+$", name)
        if m:
            entry = films.setdefault(m.group(1), {"id": None, "slug": m.group(1),
                                                  "title": m.group(1), "files": []})
            entry["files"].append(name)
    return list(films.values())


def previous_films(data_dir):
    cur = os.path.join(data_dir, "current")
    return read_manifest(cur) if os.path.isdir(cur) else []


def check_drop(previous_count, new_count, what="films"):
    """Raise SuspiciousUpdate if there are more than MAX_ITEM_DROP fewer films than last time."""
    drop = previous_count - new_count
    if MAX_ITEM_DROP and drop > MAX_ITEM_DROP:
        raise SuspiciousUpdate(
            f"only {new_count} {what} this time against {previous_count} last time "
            f"(a drop of {drop}; MAX_ITEM_DROP is {MAX_ITEM_DROP}) - assuming something went "
            f"wrong and keeping the previous images. If the drop is genuine, run it with --force")


def build_generation(session, out_dir, previous_count=None):
    """Scrape and write a full image set into out_dir. Returns the list of films written."""
    films = parse_listing(fetch(session, LISTING_URL).text)
    log.info("Listing shows %d films", len(films))
    if not films:
        raise RuntimeError("no films found in listing - page layout may have changed "
                           "(expected a 'var Events = {...}' block in the page)")
    if previous_count is not None:
        check_drop(previous_count, len(films), "films in the listing")    # fail before downloading

    written = []
    total = len(films)
    for n, film in enumerate(films, 1):
        log.info("(%d/%d) Retrieving %s", n, total, film.title)
        try:
            if not film.showings:                       # fallback: the film's own page
                time.sleep(REQUEST_DELAY)
                film.showings = parse_showings(fetch(session, film.detail_url).text)
            time.sleep(REQUEST_DELAY)
            img_resp = fetch(session, film.image_url)
            base = f"{n:02d}_{slugify(film.title)}"
            ext = image_ext(film.image_url, img_resp.headers.get("Content-Type"))
            slide = compose_slide(img_resp.content, film.title, film.showings, film.rating)
            entry = film_key(film)
            entry["files"] = []
            if SAVE_POSTERS:
                name = f"{base}_a_poster{ext}"
                with open(os.path.join(out_dir, name), "wb") as f:
                    f.write(img_resp.content)
                entry["files"].append(name)
            name = f"{base}_b_info.jpg"
            slide.save(os.path.join(out_dir, name), quality=92)
            entry["files"].append(name)
            written.append(entry)
            log.info("(%d/%d) Done: %s", n, total, describe_showings(film.showings))
        except Exception as e:                      # one bad film must not sink the run
            log.warning("(%d/%d) Skipped %s: %s", n, total, film.title, e)
    if not written:
        raise RuntimeError("every film failed")
    if len(written) < len(films):
        log.warning("%d of %d films could not be processed", len(films) - len(written), len(films))
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"created": datetime.now(TZ).isoformat(timespec="seconds"),
                   "films": written}, f, indent=1, ensure_ascii=False)
    return written


def archive_removed(data_dir, old_dir, old_films, new_films):
    """Copy the images of films that are no longer on the schedule into DATA_DIR/archive/<date>/."""
    new_ids = {f["id"] for f in new_films if f.get("id")}
    new_slugs = {f["slug"] for f in new_films}
    day_dir = os.path.join(data_dir, "archive", datetime.now(TZ).strftime("%Y-%m-%d"))
    moved = []
    for film in old_films:
        if (film.get("id") and film["id"] in new_ids) or film["slug"] in new_slugs:
            continue
        for name in film["files"]:
            src = os.path.join(old_dir, name)
            if not os.path.isfile(src):
                continue
            os.makedirs(day_dir, exist_ok=True)
            dest = os.path.join(day_dir, name)
            k = 1
            while os.path.exists(dest):                 # same file name archived earlier today
                root, ext = os.path.splitext(name)
                dest = os.path.join(day_dir, f"{root}-{k}{ext}")
                k += 1
            shutil.copy2(src, dest)      # copy: the display may still be showing the old set
        moved.append(film["title"])
    return moved


def switch_generation(data_dir, new_dir):
    link = os.path.join(data_dir, "current")
    tmp_link = os.path.join(data_dir, ".current.new")
    if os.path.lexists(tmp_link):
        os.remove(tmp_link)
    os.symlink(os.path.basename(new_dir), tmp_link)     # relative link
    os.replace(tmp_link, link)                          # atomic
    gens = sorted(d for d in os.listdir(data_dir) if d.startswith("gen-"))
    for old in gens[:-(1 + KEEP_GENERATIONS)]:
        shutil.rmtree(os.path.join(data_dir, old), ignore_errors=True)


def run_update(data_dir=DATA_DIR, force=False):
    os.makedirs(data_dir, exist_ok=True)
    for d in os.listdir(data_dir):                      # clear half-finished earlier runs
        if d.startswith(".tmp-"):
            shutil.rmtree(os.path.join(data_dir, d), ignore_errors=True)
    old_films = previous_films(data_dir)
    old_dir = os.path.realpath(os.path.join(data_dir, "current"))
    stamp = datetime.now(TZ).strftime("%Y%m%d-%H%M%S")
    tmp_dir = os.path.join(data_dir, f".tmp-{stamp}")
    os.makedirs(tmp_dir)
    try:
        check = old_films and not force
        new_films = build_generation(make_session(), tmp_dir,
                                     len(old_films) if check else None)
        if check:
            check_drop(len(old_films), len(new_films))
        final = os.path.join(data_dir, f"gen-{stamp}")
        os.rename(tmp_dir, final)
        archived = archive_removed(data_dir, old_dir, old_films, new_films) if old_films else []
        switch_generation(data_dir, final)
        if archived:
            log.info("Archived %d film(s) no longer on the schedule: %s",
                     len(archived), ", ".join(archived))
        log.info("Update complete: %d films, %d files", len(new_films), len(os.listdir(final)))
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise


# -------------------------------------------------------------------- video
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")
VIDEO_FILES = {"plain": "slideshow.mp4", "fade": "slideshow-fade.mp4"}
VIDEO_KINDS = {"none": [], "plain": ["plain"], "fade": ["fade"], "both": ["plain", "fade"]}


def list_images(folder):
    try:
        names = [n for n in os.listdir(folder)
                 if n.lower().endswith(IMAGE_EXTS) and not n.startswith(".")]
    except OSError:
        return []
    return sorted(names, key=str.lower)


def build_playlist(film_dir, static_dir, position="after"):
    """The slides in display order: film slides, with your static images before, after or
    spread through them (the same rule as the display container)."""
    films = [os.path.join(film_dir, n) for n in list_images(film_dir)]
    statics = [os.path.join(static_dir, n) for n in list_images(static_dir)] if static_dir else []
    if not statics:
        return films
    if not films:
        return statics
    if position == "before":
        return statics + films
    if position == "spread":
        out, taken = [], 0
        for k, st in enumerate(statics):
            target = round((k + 1) * len(films) / (len(statics) + 1))
            out.extend(films[taken:target])
            taken = target
            out.append(st)
        return out + films[taken:]
    return films + statics


def _file_digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def video_fingerprint(kind, playlist, digests):
    """Changes whenever the video would come out different: the slides (their content and order)
    or any setting that affects that kind of video."""
    parts = ["v1", kind, SCREEN_W, SCREEN_H, HOLD_SECONDS, VIDEO_FPS, BACKGROUND_COLOUR]
    if kind == "fade":
        parts += [FADE_SECONDS, FADE_MODE]
    h = hashlib.sha256(repr(parts).encode())
    for path in playlist:
        h.update(f"|{os.path.basename(path)}:{digests[path]}".encode())
    return h.hexdigest()


def run_ffmpeg(args):
    """Run ffmpeg at low priority so the display keeps its CPU. Raises on failure."""
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y"] + args
    result = subprocess.run(cmd, capture_output=True, text=True,
                            preexec_fn=lambda: os.nice(10))
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr.strip()[-400:]}")


def _fit_frame(path, dest, w, h):
    """Save `path` fitted inside w x h on the background colour (as the display shows it)."""
    img = _to_rgb_on_background(Image.open(path))
    scale = min(w / img.width, h / img.height)
    img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))),
                     Image.LANCZOS)
    canvas = Image.new("RGB", (w, h), BACKGROUND_COLOUR)
    canvas.paste(img, ((w - img.width) // 2, (h - img.height) // 2))
    canvas.save(dest, quality=95)


_ENCODE = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
           "-an", "-movflags", "+faststart"]


def _still_clip(frame, seconds, out):
    run_ffmpeg(["-loop", "1", "-framerate", str(VIDEO_FPS), "-t", f"{seconds:g}", "-i", frame]
               + _ENCODE + ["-r", str(VIDEO_FPS), out])


def _fade_clip(frame_a, frame_b, seconds, out):
    kind = "fadeblack" if FADE_MODE == "black" else "fade"
    run_ffmpeg(["-loop", "1", "-framerate", str(VIDEO_FPS), "-t", f"{seconds:g}", "-i", frame_a,
                "-loop", "1", "-framerate", str(VIDEO_FPS), "-t", f"{seconds:g}", "-i", frame_b,
                "-filter_complex", f"[0:v][1:v]xfade=transition={kind}:duration={seconds:g}:offset=0"]
               + _ENCODE + ["-r", str(VIDEO_FPS), out])


def _join_clips(clips, out):
    """Join clips that were all encoded the same way, without re-encoding."""
    listing = out + ".txt"
    with open(listing, "w") as f:
        for c in clips:
            f.write("file '%s'\n" % c.replace("'", "'\\''"))
    run_ffmpeg(["-f", "concat", "-safe", "0", "-i", listing, "-c", "copy",
                "-movflags", "+faststart", out])
    os.remove(listing)


def update_videos(data_dir=DATA_DIR, video_dir=None, mode=None):
    """Make the slideshow video(s) VIDEO_MODE asks for, but only those whose slides or
    settings changed since they were last made. Returns the list of videos built."""
    video_dir = video_dir or VIDEO_DIR
    wanted = VIDEO_KINDS[mode or VIDEO_MODE]
    state_path = os.path.join(video_dir, ".video-state.json")
    try:
        with open(state_path) as f:
            state = json.load(f)
    except (OSError, ValueError):
        state = {}
    for kind, name in VIDEO_FILES.items():              # a video that is no longer wanted goes
        if kind not in wanted and (name in state or os.path.exists(os.path.join(video_dir, name))):
            try:
                os.remove(os.path.join(video_dir, name))
            except OSError:
                pass
            state.pop(name, None)
            log.info("Video: removed %s (VIDEO_MODE is %s)", name, mode or VIDEO_MODE)
    if not wanted:
        return []
    os.makedirs(video_dir, exist_ok=True)

    playlist = build_playlist(os.path.join(data_dir, "current"), STATIC_DIR, STATIC_POSITION)
    if not playlist:
        log.warning("Video: no slides to make a video from")
        return []
    digests = {p: _file_digest(p) for p in playlist}
    prints = {k: video_fingerprint(k, playlist, digests) for k in wanted}
    todo = [k for k in wanted
            if state.get(VIDEO_FILES[k]) != prints[k]
            or not os.path.exists(os.path.join(video_dir, VIDEO_FILES[k]))]
    if not todo:
        log.info("Video: up to date (slides and settings unchanged)")
        return []
    if not shutil.which("ffmpeg"):
        log.warning("Video: ffmpeg is not installed, cannot make %s", ", ".join(VIDEO_FILES[k] for k in todo))
        return []

    started = time.time()
    w, h = SCREEN_W // 2 * 2, SCREEN_H // 2 * 2         # video needs even sizes
    for d in os.listdir(video_dir):
        if d.startswith(".build-"):
            shutil.rmtree(os.path.join(video_dir, d), ignore_errors=True)
    work = tempfile.mkdtemp(prefix=".build-", dir=video_dir)
    built = []
    try:
        log.info("Video: building %s from %d slides (this can take several minutes on a Pi)",
                 ", ".join(VIDEO_FILES[k] for k in todo), len(playlist))
        frames = []
        for i, path in enumerate(playlist):
            frame = os.path.join(work, f"frame{i:04d}.jpg")
            _fit_frame(path, frame, w, h)
            frames.append(frame)
        holds = []
        for i, frame in enumerate(frames):
            clip = os.path.join(work, f"hold{i:04d}.mp4")
            _still_clip(frame, HOLD_SECONDS, clip)
            holds.append(clip)
        for kind in todo:
            sequence = holds
            if kind == "fade" and FADE_SECONDS > 0 and len(frames) > 1:
                sequence = []
                for i, hold in enumerate(holds):
                    sequence.append(hold)
                    if i + 1 < len(frames):
                        clip = os.path.join(work, f"fade{i:04d}.mp4")
                        _fade_clip(frames[i], frames[i + 1], FADE_SECONDS, clip)
                        sequence.append(clip)
            out = os.path.join(work, VIDEO_FILES[kind])
            _join_clips(sequence, out)
            os.replace(out, os.path.join(video_dir, VIDEO_FILES[kind]))      # atomic
            state[VIDEO_FILES[kind]] = prints[kind]
            built.append(VIDEO_FILES[kind])
            log.info("Video: %s done (%.1f MB)", VIDEO_FILES[kind],
                     os.path.getsize(os.path.join(video_dir, VIDEO_FILES[kind])) / 1e6)
        log.info("Video: finished in %.0f s", time.time() - started)
    finally:
        shutil.rmtree(work, ignore_errors=True)
        with open(state_path, "w") as f:
            json.dump(state, f, indent=1)
    return built


def make_videos():
    """Never let a video problem upset the image update."""
    try:
        update_videos(DATA_DIR)
    except Exception:
        log.exception("Video: could not be made (the slides are unaffected)")


def seconds_until_next_run(now=None):
    """Seconds until the next of the RUN_AT times (today's remaining ones, else tomorrow's first)."""
    now = now or datetime.now(TZ)
    candidates = []
    for day in (0, 1):
        for hh, mm in RUN_TIMES:
            t = (now + timedelta(days=day)).replace(hour=hh, minute=mm, second=0, microsecond=0)
            if t > now:
                candidates.append(t)
    return (min(candidates) - now).total_seconds()


def setup_logging():
    """Log to the console and (unless LOG_FILE is off) to a rotating file, then replay any
    settings warnings so they are in the file too."""
    handlers = [logging.StreamHandler(sys.stdout)]
    file_problem = None
    if LOG_FILE.lower() not in ("off", "none", "no", "0"):
        try:
            from logging.handlers import RotatingFileHandler
            os.makedirs(os.path.dirname(LOG_FILE) or ".", exist_ok=True)
            handlers.append(RotatingFileHandler(LOG_FILE, maxBytes=2_000_000, backupCount=5,
                                                encoding="utf-8"))
        except OSError as e:
            file_problem = f"cannot write the log file {LOG_FILE}: {e} - logging to the console only"
    logging.basicConfig(level=logging.INFO, handlers=handlers, force=True,
                        format="%(asctime)s %(levelname)s %(message)s")
    if file_problem:
        log.warning(file_problem)
    for message in STARTUP_WARNINGS:
        log.warning("Setting: %s", message)


def has_images(data_dir=DATA_DIR):
    cur = os.path.join(data_dir, "current")
    return os.path.isdir(cur) and bool(os.listdir(cur))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="update now and exit")
    ap.add_argument("--force", action="store_true",
                    help="skip the MAX_ITEM_DROP safety check (for a genuine big drop)")
    ap.add_argument("--version", action="version", version=f"empire-kiosk-updater {__version__}")
    args = ap.parse_args()
    setup_logging()
    log.info("Empire kiosk updater v%s starting (updates at %s %s)",
             __version__, RUN_AT, TZ.key)

    if args.once:
        try:
            run_update(force=args.force)
        except Exception:
            log.exception("update failed - previous images kept")
            sys.exit(1)
        make_videos()
        return

    failed = False
    if not has_images():
        try:
            run_update()
        except Exception:
            log.exception("initial update failed")
            failed = True
    if has_images():
        make_videos()                       # also picks up a changed VIDEO_MODE after a restart
    while True:
        wait = RETRY_MINUTES * 60 if failed else seconds_until_next_run()
        log.info("Next update in %.1f hours", wait / 3600)
        time.sleep(wait)
        try:
            run_update()
            failed = False
            make_videos()
        except SuspiciousUpdate as e:
            # Retrying every few minutes won't change the answer; wait for the next scheduled run.
            log.error("update NOT applied: %s (to accept it now: "
                      "docker compose exec updater python updater.py --once --force)", e)
            failed = False
        except Exception:
            log.exception("update failed - keeping previous images, retrying in %d min",
                          RETRY_MINUTES)
            failed = True


if __name__ == "__main__":
    main()
