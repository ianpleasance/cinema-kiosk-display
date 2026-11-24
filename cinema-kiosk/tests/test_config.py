"""Settings: the .env file, docker-compose wiring, and tolerant parsing."""
import importlib
import os
import re
import subprocess
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "updater"))
sys.path.insert(0, os.path.join(ROOT, "display"))


def read_env_file():
    out = {}
    for line in open(os.path.join(ROOT, ".env")):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        assert re.fullmatch(r"[A-Z_]+=[^\s\"\'#]*", line), f"bad .env line: {line!r}"
        k, v = line.split("=", 1)
        out[k] = v
    return out


def test_env_file_keys_are_all_used():
    keys = read_env_file()
    code = open(os.path.join(ROOT, "updater", "updater.py")).read() + \
        open(os.path.join(ROOT, "display", "display.py")).read()
    for k in keys:
        assert re.search(rf'env(?:_\w+)?\(\s*"{k}"', code), f"{k} is in .env but no code reads it"


def test_env_file_values_load_cleanly():
    """Loading the real .env values must give exactly the documented defaults."""
    keys = read_env_file()
    saved = {k: os.environ.get(k) for k in keys}
    try:
        os.environ.update(keys)
        import updater, display
        importlib.reload(updater)
        importlib.reload(display)
        assert updater.TIME_FORMAT == "12h" and updater.RUN_AT == "03:30"
        assert updater.RETRY_MINUTES == 30 and updater.REQUEST_DELAY == 0.5
        assert updater.MAX_ITEM_DROP == 5 and updater.LOG_FILE == "/logs/updater.log"
        assert updater.RUN_TIMES == [(3, 30)] and updater.VIDEO_MODE == "none"
        assert updater.HOLD_SECONDS == 10 and updater.FADE_SECONDS == 1.0 and updater.FADE_MODE == "cross"
        assert (updater.SCREEN_W, updater.SCREEN_H) == (1920, 1080)
        assert str(updater.TZ) == "Europe/London"
        assert updater.LISTING_URL.startswith("https://empire-theatre.co.uk/")
        assert display.HOLD_SECONDS == 10 and display.FADE_SECONDS == 1.0
        assert display.FADE_MODE == "cross" and display.SHUFFLE is False
        assert updater.SAVE_POSTERS is True and display.STATIC_POSITION == "after"
        assert updater.DAYS_AHEAD == 0 and updater.SHOW_RATING is True
        assert updater.TEXT_COLOUR == (255, 255, 255) and updater.BACKGROUND_COLOUR == (0, 0, 0)
        assert updater.BADGE_COLOUR == (200, 16, 46) and updater.BADGE_TEXT_COLOUR == (255, 255, 255)
        assert updater.POSTER_WIDTH_PERCENT == 66.67
        assert (updater.TITLE_SIZE_MAX, updater.TITLE_SIZE_MIN,
                updater.DATE_SIZE_MAX, updater.DATE_SIZE_MIN) == (88, 40, 56, 30)
        assert updater.FONT_BOLD.endswith("DejaVuSans-Bold.ttf") and updater.FONT_REG.endswith("DejaVuSans.ttf")
        assert display.BACKGROUND_COLOUR == (0, 0, 0)
        assert round(1920 * updater.POSTER_WIDTH_PERCENT / 100) == 1280         # still exactly two thirds
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_tolerant_parsing():
    saved = dict(os.environ)
    try:
        os.environ.update({"TZ": "", "RUN_AT": "25:99", "TIME_FORMAT": '"24H"\r',
                           "HOLD_SECONDS": " 7 ", "FADE_MODE": "sideways", "SHUFFLE": "1\r",
                           "LISTING_URL": "'https://example.test/x'", "STATIC_POSITION": "middle",
                           "SAVE_POSTERS": "0",
                           "TEXT_COLOUR": "#fc0", "BADGE_COLOUR": "zzz", "BACKGROUND_COLOUR": "112233",
                           "POSTER_WIDTH_PERCENT": "5", "TITLE_SIZE_MIN": "100", "DATE_SIZE_MAX": "abc",
                           "DAYS_AHEAD": "-3", "FONT_BOLD": "/nope/missing.ttf",
                           "FONT_REG": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"})
        import updater, display
        importlib.reload(updater)
        importlib.reload(display)
        assert str(updater.TZ) == "Europe/London"            # blank -> default
        assert updater.RUN_AT == "03:30"                      # invalid -> default
        assert updater.TIME_FORMAT == "24h"                   # quotes / CR / case tolerated
        assert updater.LISTING_URL == "https://example.test/x"
        assert display.HOLD_SECONDS == 7.0
        assert display.FADE_MODE == "cross"                   # invalid -> default
        assert display.SHUFFLE is True
        assert display.STATIC_POSITION == "after"             # invalid -> default
        assert updater.SAVE_POSTERS is False
        assert updater.TEXT_COLOUR == (255, 204, 0)               # #fc0 shorthand, # tolerated
        assert updater.BADGE_COLOUR == (200, 16, 46)              # invalid -> default
        assert updater.BACKGROUND_COLOUR == (17, 34, 51) and display.BACKGROUND_COLOUR == (17, 34, 51)
        assert updater.POSTER_WIDTH_PERCENT == 66.67              # out of range -> default
        assert (updater.TITLE_SIZE_MIN, updater.TITLE_SIZE_MAX) == (40, 88)   # min > max -> defaults
        assert updater.DATE_SIZE_MAX == 56                        # not a number -> default
        assert updater.DAYS_AHEAD == 0                            # negative -> default
        assert updater.FONT_BOLD.endswith("DejaVuSans-Bold.ttf")  # missing font -> default
        assert updater.FONT_REG.endswith("DejaVuSans-Bold.ttf")   # a valid custom font is accepted
    finally:
        os.environ.clear()
        os.environ.update(saved)
        import updater, display
        importlib.reload(updater)
        importlib.reload(display)


def test_compose_uses_env_file():
    import yaml
    c = yaml.safe_load(open(os.path.join(ROOT, "docker-compose.yml")))
    for name in ("updater", "display"):
        svc = c["services"][name]
        assert svc.get("env_file") in (".env", [".env"]), name
        assert "environment" not in svc, f"{name} still has inline settings"
    assert "group_add" not in c["services"]["display"]
    assert "./static:/static:ro" in " ".join(c["services"]["display"]["volumes"])
    assert os.path.isdir(os.path.join(ROOT, "static"))
    assert "./fonts:/fonts:ro" in " ".join(c["services"]["updater"]["volumes"])
    assert os.path.isdir(os.path.join(ROOT, "fonts"))


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(name, "ok")
