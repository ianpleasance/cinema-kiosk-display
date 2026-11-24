"""Offline test: HTML shaped like the real Savoy/Empire pages, fake posters, no network."""
import io
import os
import sys
import tempfile

from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "updater"))
import updater  # noqa: E402

DEFAULT_TIME_FORMAT = updater.TIME_FORMAT        # value before any test changes it

import json as _json


def _perf(date, readable, time_):
    return {"ID": 1, "StartDate": date, "ReadableDate": readable,
            "StartTimeAndNotes": time_, "StartTime": time_.replace(":", "")[:4]}


_EVENTS = {"Events": [
    {"ID": 100, "Title": "Ghosts: Possession of Button House", "ImageURL": "https://images.x/ETH/1.jpg",
     "Rating": "<img class=\"film-rating\" src=\"https://images.x/bbfc/lrg/15.png\" alt=\"BBFC Rating: (15)\"/>",
     "URL": "https://empire-theatre.co.uk/EmpireTheatre.dll/WhatsOn?f=100", "Synopsis": "It's \"quoted\" {braces} [x]",
     "Performances": [_perf("2099-12-02", "Wed 2 Dec", "14:30"), _perf("2099-11-28", "Sat 28 Nov", "14:30"),
                      _perf("2099-11-28", "Sat 28 Nov", "10:30"), _perf("2000-01-01", "Sat 1 Jan", "19:00")]},
    {"ID": 200, "Title": "Very Long Event Title That Needs Wrapping Across Several Lines Of The Panel",
     "ImageURL": "/img/2.png", "URL": "WhatsOn?f=200", "Performances": []},      # dates via fallback page
    {"ID": 300, "Title": "No poster", "ImageURL": "", "Performances": [_perf("2099-12-01", "Tue 1 Dec", "19:00")]},
]}

# Like the real page: the list container is empty and the data sits in an inline script.
LISTING = ("<html><body><div id=\"whats-on-list\" class=\"columns is-multiline\"></div>"
           "<script>\r\n  var Events = " + _json.dumps(_EVENTS) + ";\r\n  function x(){return null;}\r\n</script>"
           "</body></html>")

DETAIL = """
<div class="programme-performances"><ul class="performances">
 <li class="performance columns"><span class="date column is-12">Sat 28 Nov</span>
   <span class="perf-time">10:30</span><a class="button booking" href="#"><span class="time">Book Now</span></a>
   <span class="perf-time">14:30</span><a class="button booking" href="#"><span class="time">Book Now</span></a></li>
 <li class="performance columns"><span class="date column is-12">Wed 2 Dec</span>
   <span class="perf-time">19:00</span><a class="button booking" href="#"><span class="time">Book Now</span></a></li>
</ul></div>
<div class="programme-performances"><ul class="performances"><li class="performance"><span class="date">DUPLICATE</span><span class="perf-time">00:00</span></li></ul></div>
"""


def jpeg(w, h, colour):
    b = io.BytesIO()
    Image.new("RGB", (w, h), colour).save(b, "JPEG")
    return b.getvalue()


def png_alpha(w, h):
    b = io.BytesIO()
    Image.new("RGBA", (w, h), (200, 30, 30, 128)).save(b, "PNG")
    return b.getvalue()


def test_parse():
    updater.TIME_FORMAT = "24h"                     # these checks use 24h times
    try:
        _check_parse()
    finally:
        updater.TIME_FORMAT = DEFAULT_TIME_FORMAT


def _check_parse():
    films = updater.parse_listing(LISTING, today="2026-11-20")
    assert [f.id for f in films] == ["100", "200"]               # no-poster event skipped
    assert films[0].title == "Ghosts: Possession of Button House"
    assert films[1].image_url == "https://empire-theatre.co.uk/img/2.png"
    # grouped per day, in date order, times in order, past showing dropped
    assert films[0].showings == [("Sat 28 Nov", ["10:30", "14:30"]), ("Wed 2 Dec", ["14:30"])]
    assert films[1].showings == []
    assert films[0].rating == "15" and films[1].rating == ""
    assert updater.parse_listing("<html>no data</html>") == []
    sh = updater.parse_showings(DETAIL)                           # fallback parser
    assert sh == [("Sat 28 Nov", ["10:30", "14:30"]), ("Wed 2 Dec", ["19:00"])]


def test_clean_text():
    c = updater.clean_text
    assert c("Tom &amp; Jerry") == "Tom & Jerry"
    assert c("Tom &amp;amp; Jerry") == "Tom & Jerry"            # double encoded
    assert c("Rock &#39;n&#39; Roll &quot;Live&quot;") == "Rock 'n' Roll \"Live\""
    assert c("Caf&eacute;   Night\n") == "Café Night"
    assert c("A &lt; B") == "A < B"
    assert c(None) == ""


def _measure(w=640, h=1080):
    from PIL import Image, ImageDraw
    return ImageDraw.Draw(Image.new("RGB", (w, h))), updater._font(updater.FONT_BOLD, 60)


def test_wrap_breaks():
    d, f = _measure()
    # fits -> untouched, '.' and ':' are NOT forced breaks
    assert updater._wrap(d, "Dr. Who: Pit", f, 560) == ["Dr. Who: Pit"]
    # too long for one line -> breaks after '.' / ':' rather than splitting letters
    rep = {}
    lines = updater._wrap(d, "Chuckl.Halstead.November:2026", f, 560, rep)
    assert len(lines) > 1 and not rep.get("hard"), lines
    assert "".join(lines) == "Chuckl.Halstead.November:2026"
    assert all(l.endswith((".", ":")) for l in lines[:-1]), lines
    # soft=False (used for times): never break inside "19:00"
    lines = updater._wrap(d, "10:30, 14:30, 19:00, 21:30", f, 400, soft=False)
    assert all(":" not in l[-1] and len(l.split()[-1]) >= 5 for l in lines), lines
    # a single unbreakable monster word still gets split (last resort) and flagged
    rep = {}
    lines = updater._wrap(d, "Supercalifragilisticexpialidocious", f, 560, rep)
    assert rep.get("hard") and len(lines) > 1
    assert "".join(lines) == "Supercalifragilisticexpialidocious"
    assert all(d.textlength(l, font=f) <= 560 for l in lines)


def test_vertical_centering():
    import numpy as np
    for title, showings in [("Wicker", [("Fri 27 Nov", ["19:30"])]),
                            ("Ghosts: Possession of Button House",
                             [("Sat 21 Nov", ["19:30"]), ("Wed 25 Nov", ["14:30"])]),
                            ("Chuckl.Halstead November 2026", [("Fri 20 Nov", ["19:30"])])]:
        panel = updater.render_info_panel(640, 1080, title, showings)
        a = np.array(panel).sum(axis=2)
        rows = np.where(a.max(axis=1) > 0)[0]
        top, bottom = rows.min(), 1080 - 1 - rows.max()
        assert abs(top - bottom) <= 40, (title, top, bottom)     # glyph ascent/descent slack
        assert top > 40 and bottom > 40, (title, top, bottom)    # and nothing hits the edges


def test_entities_end_to_end():
    html = LISTING.replace("Ghosts: Possession of Button House", "Tom &amp;amp; Jerry: Live &amp; Loud")
    films = updater.parse_listing(html, today="2026-11-20")
    assert films[0].title == "Tom & Jerry: Live & Loud"


def test_time_format():
    f = updater.format_times
    old = updater.TIME_FORMAT
    try:
        updater.TIME_FORMAT = "12h"
        assert [f(t) for t in ("19:30", "10:30", "12:00", "00:15", "12:45", "09:05", "23:59")] == \
            ["7:30pm", "10:30am", "12:00pm", "12:15am", "12:45pm", "9:05am", "11:59pm"]
        assert f("19:30 AF") == "7:30pm AF"                 # notes survive
        assert f("Doors 18:00, film 19:30") == "Doors 6:00pm, film 7:30pm"
        updater.TIME_FORMAT = "24h"
        assert f("19:30") == "19:30" and f("19:30 AF") == "19:30 AF"
        # end to end through the listing parser
        updater.TIME_FORMAT = "12h"
        films = updater.parse_listing(LISTING, today="2026-11-20")
        assert films[0].showings == [("Sat 28 Nov", ["10:30am", "2:30pm"]), ("Wed 2 Dec", ["2:30pm"])]
        updater.TIME_FORMAT = "24h"
        films = updater.parse_listing(LISTING, today="2026-11-20")
        assert films[0].showings == [("Sat 28 Nov", ["10:30", "14:30"]), ("Wed 2 Dec", ["14:30"])]
    finally:
        updater.TIME_FORMAT = old
    assert DEFAULT_TIME_FORMAT == "12h"                      # the default


def test_parse_rating():
    r = updater.parse_rating
    assert r('<img class="film-rating" src="https://x/bbfc/lrg/PG.png" alt="BBFC Rating: (PG)"/>') == "PG"
    assert r('<img alt="BBFC Rating: (12A)">') == "12A"
    assert r('<img src="https://x/bbfc/lrg/18.png">') == "18"            # falls back to the file name
    assert r('<img alt="Rating: (Exempt)">') == ""                        # too long for a badge
    assert r("") == "" and r(None) == ""


def _bands(a):
    rows = (a.max(axis=1) > 0)
    out, start = [], None
    for y, on in enumerate(rows):
        if on and start is None:
            start = y
        if not on and start is not None:
            out.append((start, y)); start = None
    return out


def test_times_align_and_badge():
    import numpy as np
    shows = [("Sat 8 Nov", ["19:30"]), ("Wednesday 25 Nov", ["14:30"]),
             ("Fri 4 Dec", ["10:30", "19:30"]), ("Sun 6 Dec", ["14:30"])]
    panel = updater.render_info_panel(640, 1080, "Hexed", shows, "12A")
    arr = np.array(panel).astype(int)
    white = (arr.min(axis=2) > 200)
    red = (arr[:, :, 0] > 150) & (arr[:, :, 1] < 80) & (arr[:, :, 2] < 100)
    assert red.sum() > 5000                                   # the red circle is there
    ys, xs = np.where(red)
    assert xs.min() >= 40 and ys.min() > 40                   # inside the margins
    bands = [b for b in _bands(white.astype(int)) if b[0] > ys.max() + 5]   # below the badge
    row_bands = bands[-4:]                                     # the four showing rows
    starts = []
    for y0, y1 in row_bands:
        cols = np.where(white[y0:y1].any(axis=0))[0]
        gaps = np.where(np.diff(cols) > 25)[0]                 # the gap between date and times
        assert len(gaps), "date and time columns not separated"
        starts.append(cols[gaps[0] + 1])
    assert max(starts) - min(starts) <= 1, starts              # all times start at the same x
    # no rating -> no red anywhere
    panel2 = updater.render_info_panel(640, 1080, "Hexed", shows, "")
    a2 = np.array(panel2).astype(int)
    assert not ((a2[:, :, 0] > 150) & (a2[:, :, 1] < 80)).any()


def test_compose():
    out = tempfile.mkdtemp()
    cases = {
        "portrait": (jpeg(600, 900, (30, 90, 160)), "Wicker", [("Fri 27 Nov", ["19:30"])]),
        "wide": (jpeg(1600, 900, (20, 120, 60)), "Landscape Poster", [("Sat 28 Nov", ["10:30", "14:30"])]),
        "alpha": (png_alpha(500, 700), "Very Long Event Title That Needs Wrapping Across Several Lines Of The Panel",
                  [("Mon 1 Dec", ["19:00"])]),
        "many": (jpeg(600, 900, (120, 40, 120)), "Matinee Season",
                 [(f"Day {i} Dec", ["10:30", "14:30", "19:00"]) for i in range(1, 30)]),
        "none": (jpeg(600, 900, (90, 90, 20)), "No Dates Yet", []),
    }
    for name, (data, title, showings) in cases.items():
        im = updater.compose_slide(data, title, showings)
        assert im.size == (1920, 1080)
        # right third background is black where there is no text (bottom-right corner)
        assert im.getpixel((1900, 1070)) == (0, 0, 0)
        # left-most column is black bars or poster, never panel
        im.save(os.path.join(out, f"{name}.jpg"), quality=90)
    print("slides written to", out)
    return out


if __name__ == "__main__":
    test_clean_text()
    test_wrap_breaks()
    test_vertical_centering()
    test_entities_end_to_end()
    test_parse()
    test_time_format()
    test_parse_rating()
    test_times_align_and_badge()
    print("parse ok")
    test_compose()
    print("compose ok")
