#!/usr/bin/env python3
"""Empire Theatre kiosk updater.

Once a day (and on start-up if there is nothing to show yet) this:
  1. reads the What's On listing,
  2. for each film downloads the poster and reads the showing dates from the
     film's own page,
  3. saves the original poster plus a 1920x1080 "info" slide (poster scaled to
     full height in the left two thirds, black panel with the title and show
     dates in white on the right third),
  4. atomically switches the display over to the new set of images.

Output layout (DATA_DIR is a volume shared with the display container):
    DATA_DIR/gen-<timestamp>/   a complete set of images
    DATA_DIR/current            symlink -> the newest gen-* directory
The old generation is only deleted after `current` points at the new one, and
nothing is switched if the scrape fails, so the screen never goes blank.
"""
import argparse
import io
import json
import logging
import mimetypes
import os
import re
import shutil
import sys
import time
from datetime import datetime, timedelta
from html import unescape
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont, ImageOps

# ----------------------------------------------------------------- settings
TIME_FORMAT = os.environ.get("TIME_FORMAT", "12h").lower()   # "12h" -> 7:30pm   "24h" -> 19:30
LISTING_URL = os.environ.get(
    "LISTING_URL", "https://empire-theatre.co.uk/EmpireTheatre.dll/WhatsOn")
DATA_DIR = os.environ.get("DATA_DIR", "/data")
TZ = ZoneInfo(os.environ.get("TZ", "Europe/London"))
RUN_AT = os.environ.get("RUN_AT", "03:30")            # HH:MM local time
RETRY_MINUTES = int(os.environ.get("RETRY_MINUTES", "30"))
SCREEN_W = int(os.environ.get("SCREEN_W", "1920"))
SCREEN_H = int(os.environ.get("SCREEN_H", "1080"))
FONT_BOLD = os.environ.get(
    "FONT_BOLD", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
FONT_REG = os.environ.get(
    "FONT_REG", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
REQUEST_DELAY = float(os.environ.get("REQUEST_DELAY", "0.5"))
USER_AGENT = os.environ.get(
    "USER_AGENT", "EmpireKiosk/1.0 (cinema foyer display; daily refresh)")
KEEP_GENERATIONS = 1                                   # old sets kept besides current

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


def parse_listing(html, base_url=LISTING_URL, today=None):
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

    films, seen = [], set()
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
        film.showings = group_performances(ev.get("Performances") or [], today)
        films.append(film)
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


def group_performances(performances, today):
    """[(ReadableDate, [times])] in date order, one entry per day, past days dropped."""
    perfs = sorted((p for p in performances if str(p.get("StartDate", "")) >= today),
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


RED = (200, 16, 46)
WHITE = (255, 255, 255)


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
    panel = Image.new("RGB", (width, height), (0, 0, 0))
    draw = ImageDraw.Draw(panel)
    pad, gap = 40, 36
    max_w = width - 2 * pad
    avail_h = height - 2 * pad
    badge_d = 104
    badge_h = (badge_d + 30) if rating else 0

    for title_size in range(88, 39, -2):
        tf = _font(FONT_BOLD, title_size)
        rep = {}
        t_lines = _wrap(draw, title, tf, max_w, rep)
        if (len(t_lines) > 4 or rep.get("hard")) and title_size > 40:
            continue
        t_h = len(t_lines) * int(title_size * 1.2)
        for date_size in range(56, 29, -2):
            df, rows, col_x, wrapped = _fit_dates(draw, showings, date_size, max_w)
            if wrapped and date_size > 30:
                continue                              # prefer one line per showing
            d_h = sum(max(1, len(l)) for _, l in rows) * int(date_size * 1.45)
            if badge_h + t_h + gap + d_h <= avail_h:
                return _draw_panel(panel, draw, pad, rating, badge_d, tf, t_lines, title_size,
                                   df, rows, col_x, date_size, gap)

    # Lots of showings: fixed modest sizes, truncate with "+ N more dates".
    title_size, date_size = 44, 30
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
        draw.ellipse([pad, y, pad + badge_d, y + badge_d], fill=RED)
        bf = _badge_font(draw, rating, badge_d)
        draw.text((pad + badge_d / 2, y + badge_d / 2), rating, font=bf, fill=WHITE, anchor="mm")
        y += badge_h

    for line in t_lines:
        draw.text((pad, y), line, font=tf, fill=WHITE)
        y += t_step
    y += gap
    draw.line([(pad, y - gap // 2), (pad + 120, y - gap // 2)], fill=WHITE, width=3)
    for date, time_lines in rows:
        draw.text((pad, y), date, font=df, fill=WHITE)
        for i, line in enumerate(time_lines):
            draw.text((pad + col_x, y + i * d_step), line, font=df, fill=WHITE)
        y += max(1, len(time_lines)) * d_step
    return panel


def _to_rgb_on_black(img):
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (0, 0, 0))
        bg.paste(img, mask=img.split()[-1])
        return bg
    return img.convert("RGB")


def compose_slide(poster_bytes, title, showings, rating="", w=SCREEN_W, h=SCREEN_H):
    """1920x1080 slide: poster in left 2/3 (full height, black edges), info on right 1/3."""
    left_w = round(w * 2 / 3)
    poster = _to_rgb_on_black(Image.open(io.BytesIO(poster_bytes)))
    scale = min(left_w / poster.width, h / poster.height)   # full height unless too wide
    new_size = (max(1, round(poster.width * scale)), max(1, round(poster.height * scale)))
    poster = poster.resize(new_size, Image.LANCZOS)
    canvas = Image.new("RGB", (w, h), (0, 0, 0))
    canvas.paste(poster, ((left_w - new_size[0]) // 2, (h - new_size[1]) // 2))
    canvas.paste(render_info_panel(w - left_w, h, title, showings, rating), (left_w, 0))
    return canvas


def fit_to_screen(poster_bytes, w=SCREEN_W, h=SCREEN_H):
    """Not used for saving (originals are saved untouched); handy for tests."""
    img = _to_rgb_on_black(Image.open(io.BytesIO(poster_bytes)))
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


def build_generation(session, out_dir):
    """Scrape and write a full image set into out_dir. Returns number of films written."""
    films = parse_listing(fetch(session, LISTING_URL).text)
    log.info("Listing shows %d films", len(films))
    if not films:
        raise RuntimeError("no films found in listing - page layout may have changed "
                           "(expected a 'var Events = {...}' block in the page)")

    written = 0
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
            with open(os.path.join(out_dir, f"{base}_a_poster{ext}"), "wb") as f:
                f.write(img_resp.content)
            slide.save(os.path.join(out_dir, f"{base}_b_info.jpg"), quality=92)
            written += 1
            log.info("(%d/%d) Done: %d dates", n, total, len(film.showings))
        except Exception as e:                      # one bad film must not sink the run
            log.warning("(%d/%d) Skipped %s: %s", n, total, film.title, e)
    if written == 0:
        raise RuntimeError("every film failed")
    return written


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


def run_update(data_dir=DATA_DIR):
    os.makedirs(data_dir, exist_ok=True)
    for d in os.listdir(data_dir):                      # clear half-finished earlier runs
        if d.startswith(".tmp-"):
            shutil.rmtree(os.path.join(data_dir, d), ignore_errors=True)
    stamp = datetime.now(TZ).strftime("%Y%m%d-%H%M%S")
    tmp_dir = os.path.join(data_dir, f".tmp-{stamp}")
    os.makedirs(tmp_dir)
    try:
        n = build_generation(make_session(), tmp_dir)
        final = os.path.join(data_dir, f"gen-{stamp}")
        os.rename(tmp_dir, final)
        switch_generation(data_dir, final)
        log.info("Update complete: %d films, %d files", n, len(os.listdir(final)))
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise


def seconds_until_next_run(now=None):
    now = now or datetime.now(TZ)
    hh, mm = (int(x) for x in RUN_AT.split(":"))
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def has_images(data_dir=DATA_DIR):
    cur = os.path.join(data_dir, "current")
    return os.path.isdir(cur) and bool(os.listdir(cur))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="update now and exit")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)

    if args.once:
        run_update()
        return

    failed = False
    if not has_images():
        try:
            run_update()
        except Exception:
            log.exception("initial update failed")
            failed = True
    while True:
        wait = RETRY_MINUTES * 60 if failed else seconds_until_next_run()
        log.info("Next update in %.1f hours", wait / 3600)
        time.sleep(wait)
        try:
            run_update()
            failed = False
        except Exception:
            log.exception("update failed - keeping previous images, retrying in %d min",
                          RETRY_MINUTES)
            failed = True


if __name__ == "__main__":
    main()
