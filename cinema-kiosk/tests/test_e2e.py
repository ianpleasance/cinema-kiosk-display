"""End-to-end run of the updater with the network faked out."""
import io
import os
import sys
import tempfile

from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "updater"))
import updater  # noqa: E402
from test_updater import LISTING, DETAIL, jpeg  # noqa: E402


class Resp:
    def __init__(self, text="", content=b"", ctype="text/html"):
        self.text, self.content, self.headers = text, content, {"Content-Type": ctype}


def make_fetch(fail=False):
    def fake(session, url, **kw):
        if fail:
            raise RuntimeError("site down")
        if url.endswith("/WhatsOn"):
            return Resp(text=LISTING)
        if "?f=" in url:
            return Resp(text=DETAIL)
        return Resp(content=jpeg(600, 900, (10, 60, 120)), ctype="image/jpeg")
    return fake


def main():
    updater.REQUEST_DELAY = 0
    data = tempfile.mkdtemp()

    updater.fetch = make_fetch()
    updater.run_update(data)
    cur = os.path.join(data, "current")
    files = sorted(os.listdir(cur))
    print("first run:", files)
    assert len(files) == 4 and files[0].startswith("01_ghosts") and files[3].startswith("02_very-long") and files[3].endswith("_b_info.jpg"), files
    assert Image.open(os.path.join(cur, files[1])).size == (1920, 1080)
    first_target = os.readlink(cur)

    # second run (new generation), old one kept as a fallback, symlink moved
    import time; time.sleep(1.1)
    updater.run_update(data)
    assert os.readlink(cur) != first_target
    assert len([d for d in os.listdir(data) if d.startswith("gen-")]) == 2

    # third run: failure must leave `current` untouched and leave no temp dirs
    target = os.readlink(cur)
    updater.fetch = make_fetch(fail=True)
    try:
        updater.run_update(data)
        raise SystemExit("expected failure")
    except RuntimeError as e:
        print("failure handled:", e)
    assert os.readlink(cur) == target
    assert not [d for d in os.listdir(data) if d.startswith(".tmp-")]
    assert updater.has_images(data)

    # scheduler maths
    s = updater.seconds_until_next_run()
    assert 0 < s <= 86400
    print("e2e ok")


if __name__ == "__main__":
    main()
