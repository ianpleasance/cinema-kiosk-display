"""Offline test: HTML shaped like the real Savoy/Empire pages, fake posters, no network."""
import io
import os
import sys
import tempfile

from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "updater"))
import updater  # noqa: E402

DEFAULT_TIME_FORMAT = updater.TIME_FORMAT        # value before any test changes it
updater.DATE_MODE = "plain"                      # most tests expect 'Sat 28 Nov'; the ordinal ones switch it

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


def test_describe_showings():
    d = updater.describe_showings
    assert d([]) == "no dates"
    assert d([("Sat 21 Nov", ["7:30pm"])]) == "1 date: Sat 21 Nov 7:30pm"
    assert d([("Sat 21 Nov", ["7:30pm"]), ("Wed 25 Nov", ["10:30am", "2:30pm"])]) == \
        "2 dates: Sat 21 Nov 7:30pm; Wed 25 Nov 10:30am, 2:30pm"


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


import contextlib


@contextlib.contextmanager
def _set(**kw):
    """Temporarily override updater settings."""
    old = {k: getattr(updater, k) for k in kw}
    for k, v in kw.items():
        setattr(updater, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(updater, k, v)


def test_colours_and_badge():
    import numpy as np
    with _set(TEXT_COLOUR=(255, 200, 0), BACKGROUND_COLOUR=(10, 20, 90),
              BADGE_COLOUR=(0, 160, 0), BADGE_TEXT_COLOUR=(0, 0, 0)):
        panel = updater.render_info_panel(640, 1080, "Hexed", [("Sat 28 Nov", ["7:30pm"])], "PG")
        a = np.array(panel).astype(int)
        assert tuple(a[1070, 630]) == (10, 20, 90)                      # background colour
        cols = {tuple(c) for c in a.reshape(-1, 3)}
        assert (255, 200, 0) in cols                                    # text colour
        assert (0, 160, 0) in cols                                      # badge colour
        assert (0, 0, 0) in cols                                        # badge text colour
        assert (255, 255, 255) not in cols and (200, 16, 46) not in cols  # no old hard-coded colours
    # poster edges use the background colour too
    with _set(BACKGROUND_COLOUR=(10, 20, 90)):
        im = updater.compose_slide(jpeg(600, 900, (200, 0, 0)), "X", [], "")
        assert im.getpixel((5, 500)) == (10, 20, 90)                    # bar left of the poster


def test_show_rating_flag():
    import numpy as np

    def red_pixels(flag):
        with _set(SHOW_RATING=flag):
            im = updater.compose_slide(jpeg(600, 900, (30, 90, 160)), "Wicker", [("Fri 27 Nov", ["7:30pm"])], "15")
        a = np.array(im).astype(int)[:, 1280:]
        return int(((a[:, :, 0] > 150) & (a[:, :, 1] < 80) & (a[:, :, 2] < 100)).sum())
    assert red_pixels(True) > 5000
    assert red_pixels(False) == 0


def test_poster_width():
    import numpy as np
    shows = [("Fri 27 Nov", ["7:30pm"])]
    im = updater.compose_slide(jpeg(600, 900, (0, 0, 255)), "Wicker", shows, "15")   # default: two thirds
    a = np.array(im).astype(int)
    white = a.min(axis=2) > 200
    assert white[:, 1280:].any() and not white[:, :1279].any()          # text only in the right third
    with _set(POSTER_WIDTH_PERCENT=50.0):
        im = updater.compose_slide(jpeg(600, 900, (0, 0, 255)), "Wicker", shows, "15")
        a = np.array(im).astype(int)
        white = a.min(axis=2) > 200
        assert not white[:, :950].any() and white[:, 960:].any()        # text starts at 960 now
        px = im.getpixel((480, 540))
        assert px[2] > 200 and px[0] < 40                               # poster centred in the left half
        assert im.getpixel((900, 540)) == (0, 0, 0)                     # gap between poster and text


def test_text_size_limits():
    shows = [("Sat 28 Nov", ["7:30pm"])]

    def title_height(**kw):
        import numpy as np
        with _set(**kw):
            panel = updater.render_info_panel(640, 1080, "Hexed", shows, "")
        return (lambda b: b[0][1] - b[0][0])(_bands(np.array(panel).sum(axis=2)))
    big, small = title_height(), title_height(TITLE_SIZE_MAX=50)
    assert big > small * 1.5, (big, small)
    # sizes tried: largest first, always ends on the minimum
    assert updater._sizes(88, 40)[0] == 88 and updater._sizes(88, 40)[-1] == 40
    assert updater._sizes(51, 40)[-1] == 40 and updater._sizes(40, 40) == [40]
    # a long title can never shrink below the minimum: it wraps instead (and stays inside the panel)
    with _set(TITLE_SIZE_MIN=60, TITLE_SIZE_MAX=60):
        panel = updater.render_info_panel(640, 1080, "A Very Long Title For The Foyer Screen Test", shows, "PG")
        assert panel.size == (640, 1080)


def test_days_ahead():
    d = lambda films: [x for x, _ in films[0].showings]                  # noqa: E731
    with _set(TIME_FORMAT="24h"):
        everything = updater.parse_listing(LISTING, today="2099-11-27", days_ahead=0)
        assert [f.id for f in everything] == ["100", "200"]
        assert d(everything) == ["Sat 28 Nov", "Wed 2 Dec"]
        assert d(updater.parse_listing(LISTING, today="2099-11-27", days_ahead=3)) == ["Sat 28 Nov"]
        # 'today plus N days' is inclusive: 26th + 2 = 28th is shown
        assert updater.parse_listing(LISTING, today="2099-11-26", days_ahead=2)[0].showings
        # one day short -> that event is dropped; the one with no showings data stays (fallback page)
        assert [f.id for f in updater.parse_listing(LISTING, today="2099-11-26", days_ahead=1)] == ["200"]
        # everything already past -> dropped as well
        assert [f.id for f in updater.parse_listing(LISTING, today="2099-12-03")] == ["200"]
        # the DAYS_AHEAD setting is the default
        with _set(DAYS_AHEAD=3):
            assert d(updater.parse_listing(LISTING, today="2099-11-27")) == ["Sat 28 Nov"]


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


# ------------------------------------------------------------ dates and prices
def test_date_mode():
    assert [updater.ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22, 23, 30, 31)] == \
        ["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "23rd", "30th", "31st"]
    try:
        updater.DATE_MODE = "ordinal"
        f = updater.format_date
        assert f("Sat 21 Nov") == "Sat 21st Nov"
        assert f("Wed 2 Dec") == "Wed 2nd Dec"
        assert f("Thu 19 Dec") == "Thu 19th Dec"
        assert f("Sat 11 Jan") == "Sat 11th Jan"
        assert f("Wednesday 25 Nov") == "Wednesday 25th Nov"
        assert f("2026-11-28") == "2026-11-28"                       # an ISO fallback is left alone
        assert f("Doors 7pm") == "Doors 7pm"
        films = updater.parse_listing(LISTING, today="2099-11-27")
        assert [d for d, _ in films[0].showings] == ["Sat 28th Nov", "Wed 2nd Dec"]
        assert updater.parse_showings(DETAIL)[0][0] == "Sat 28th Nov"      # the fallback page too
        updater.DATE_MODE = "plain"
        assert f("Sat 21 Nov") == "Sat 21 Nov"
        assert [d for d, _ in updater.parse_listing(LISTING, today="2099-11-27")[0].showings] == ["Sat 28 Nov", "Wed 2 Dec"]
    finally:
        updater.DATE_MODE = "plain"
    assert os.environ.get("DATE_MODE") is None                      # and the default (no setting) is ordinal
    import subprocess
    out = subprocess.run([sys.executable, "-I", "-c",
                          "import sys; sys.path.insert(0, %r); import updater; print(updater.DATE_MODE)"
                          % os.path.join(os.path.dirname(__file__), "..", "updater")],
                         capture_output=True, text=True, env={"PATH": os.environ.get("PATH", "")}).stdout.strip()
    assert out == "ordinal", out


BOOKING = """
<html><body><h2>Wicker (15)</h2>
<p>Choose Seats</p>
<div><b>STANDARD</b><ul>
 <li><a href="javascript:AssignPersonType('284', '286', '500')">Adult (&pound;5.00)</a></li>
 <li><a href="javascript:AssignPersonType('284', '287', '500')">Child (&pound;5.00)</a></li></ul>
<b>WHEELCHAIR</b><ul>
 <li><a href="javascript:AssignPersonType('285', '286', '500')">Adult (&pound;5.00)</a></li></ul>
<a href="javascript:AssignPersonType('0', '0', '0')">Clear or Cancel</a>
<a href="/EmpireTheatre.dll/Account">Log In (&pound;99 membership)</a></div></body></html>
"""
BOOKING_MIXED = BOOKING.replace("Child (&pound;5.00)", "Child (&pound;3.50)")


def test_parse_prices_and_format():
    from decimal import Decimal as D
    assert updater.parse_prices(BOOKING) == {D("5.00")}              # repeated, "Clear" and non-ticket links ignored
    assert updater.parse_prices(BOOKING_MIXED) == {D("5.00"), D("3.50")}
    assert updater.parse_prices("<html>sold out</html>") == set()
    assert updater.parse_prices("<a href=\"javascript:AssignPersonType(1)\">Adult (&pound;1,250.00)</a>") == {D("1250.00")}
    fp = updater.format_price
    assert fp(D("5.00")) == "£5" and fp(D("16.50")) == "£16.50" and fp(D("12.5")) == "£12.50"
    assert fp(D("0.00")) == "Free" and fp(D("30")) == "£30" and fp(D("0.99")) == "£0.99"


def _perf_with_sections(pid, date, sections):
    return {"ID": pid, "StartDate": date, "ReadableDate": "x", "StartTimeAndNotes": "19:30", "StartTime": "1930",
            "URL": f"Booking?Booking=TSelectItems.TcsPerformance_{pid}.TcsSection_840",
            "Sections": [{"SectionID": s, "PriceGroupID": g} for s, g in sections]}


def test_price_pages():
    perfs = [_perf_with_sections(1, "2099-11-28", [(840, 6806)]),
             _perf_with_sections(2, "2099-12-02", [(840, 6806)]),                 # same group: one page
             _perf_with_sections(3, "2099-12-03", [(840, 292), (651371, 292)]),    # two sections: two pages
             _perf_with_sections(4, "2000-01-01", [(840, 9999)])]                  # in the past: ignored
    pages = updater.price_pages(perfs, "2099-11-27", None, "https://x.test/Empire.dll/WhatsOn")
    assert list(pages) == [(6806, 840), (292, 840), (292, 651371)]
    assert pages[(6806, 840)] == "https://x.test/Empire.dll/Booking?Booking=TSelectItems.TcsPerformance_1.TcsSection_840"
    assert pages[(292, 651371)].endswith("TcsPerformance_3.TcsSection_651371")  # the right section's page
    assert updater.price_pages([{"ID": 1, "StartDate": "2099-11-28", "Sections": [{"SectionID": 1}]}],
                               "2099-11-27", None, "https://x.test/") == {}      # no booking link: nothing to read


def test_film_price_rules():
    calls = []
    pages = {"a": BOOKING, "b": BOOKING, "mixed": BOOKING_MIXED,
             "free": BOOKING.replace("&pound;5.00", "&pound;0.00"), "closed": "<html>no tickets</html>"}
    real_fetch, real_delay, real_show = updater.fetch, updater.REQUEST_DELAY, updater.SHOW_PRICE

    def fake(session, url, **kw):
        calls.append(url)
        if url == "boom":
            raise RuntimeError("down")
        return type("R", (), {"text": pages[url]})()
    updater.fetch, updater.REQUEST_DELAY = fake, 0
    try:
        def film(*urls):
            f = updater.Film("1", "T", "i", "d")
            f.price_pages = {(i, 1): u for i, u in enumerate(urls)}
            return f
        cache = {}
        assert updater.film_price(None, film("a"), cache) == "£5"                 # one price
        assert updater.film_price(None, film("a", "b"), {}) == "£5"               # two pages, same price
        assert updater.film_price(None, film("mixed"), {}) == ""                  # adult and child differ
        assert updater.film_price(None, film("a", "mixed"), {}) == ""
        assert updater.film_price(None, film("free"), {}) == "Free"
        assert updater.film_price(None, film("closed"), {}) == ""                 # nothing found
        assert updater.film_price(None, film("a", "closed"), {}) == "£5"         # a page without prices is skipped
        assert updater.film_price(None, film("a", "boom"), {}) == ""              # can't read one: show nothing
        assert updater.film_price(None, updater.Film("1", "T", "i", "d"), {}) == ""   # no booking pages
        calls.clear()
        shared = {}
        updater.film_price(None, film("a"), shared)
        updater.film_price(None, film("a"), shared)                               # cached: not fetched twice
        assert calls == ["a"]
        updater.SHOW_PRICE = False
        calls.clear()
        assert updater.film_price(None, film("a"), {}) == "" and calls == []      # switched off: no requests
    finally:
        updater.fetch, updater.REQUEST_DELAY, updater.SHOW_PRICE = real_fetch, real_delay, real_show


def test_price_on_the_slide():
    shows = [("Fri 27 Nov", ["7:30pm"])]

    def red(im):
        return any(r > 150 and g < 60 for r, g, b in im.crop((30, 330, 220, 500)).getdata())
    def light(im, box):
        return sum(1 for p in im.crop(box).get_flattened_data() if sum(p) > 600) if hasattr(im, 'get_flattened_data') else sum(1 for p in im.crop(box).getdata() if sum(p) > 600)
    rating_only = updater.render_info_panel(640, 1080, "Wicker", shows, "15")
    both = updater.render_info_panel(640, 1080, "Wicker", shows, "15", "£5")
    price_only = updater.render_info_panel(640, 1080, "Wicker", shows, "", "£5")
    plain = updater.render_info_panel(640, 1080, "Wicker", shows)
    assert red(rating_only) and red(both) and not red(price_only) and not red(plain)
    # the price sits to the right of the circle, on the same row
    assert light(both, (180, 330, 620, 500)) > light(rating_only, (180, 330, 620, 500)) + 100
    # with no rating it takes the rating's place at the left edge
    def top(im):                       # first row with text, i.e. the top of the block
        return next(y for y in range(im.height) if light(im, (0, y, im.width, y + 1)))
    assert top(price_only) < top(plain) - 40                             # the price row makes the block taller
    assert light(price_only, (30, top(price_only), 300, top(price_only) + 100)) > 100   # price at the left edge
    # a price makes room for its row, and the long price still fits the panel
    wide = updater.render_info_panel(640, 1080, "Wicker", shows, "12A", "£1,250.50")
    assert light(wide, (180, 330, 640, 500)) > 100
    # SHOW_PRICE=0 hides it on a finished slide
    poster = jpeg(600, 900, (30, 90, 160))
    on = updater.compose_slide(poster, "Wicker", shows, "15", price="£5")
    old = updater.SHOW_PRICE
    try:
        updater.SHOW_PRICE = False
        off = updater.compose_slide(poster, "Wicker", shows, "15", price="£5")
    finally:
        updater.SHOW_PRICE = old
    assert on.tobytes() != off.tobytes()
    assert off.tobytes() == updater.compose_slide(poster, "Wicker", shows, "15").tobytes()


if __name__ == "__main__":
    test_clean_text()
    test_wrap_breaks()
    test_vertical_centering()
    test_entities_end_to_end()
    test_parse()
    test_time_format()
    test_describe_showings()
    test_colours_and_badge()
    test_show_rating_flag()
    test_poster_width()
    test_text_size_limits()
    test_days_ahead()
    test_parse_rating()
    test_times_align_and_badge()
    test_date_mode()
    test_parse_prices_and_format()
    test_price_pages()
    test_film_price_rules()
    test_price_on_the_slide()
    print("parse ok")
    test_compose()
    print("compose ok")
