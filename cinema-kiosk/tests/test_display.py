"""Tests for the display's pure logic (no pygame / screen needed)."""
import io
import os
import sys
import tempfile

from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "display"))
import display  # noqa: E402


def test_next_name():
    names = ["01_a.jpg", "01_b.jpg", "02_a.jpg"]
    assert display.next_name(names, None) == "01_a.jpg"
    assert display.next_name(names, "01_a.jpg") == "01_b.jpg"
    assert display.next_name(names, "02_a.jpg") == "01_a.jpg"       # wraps
    assert display.next_name(names, "01_aa.jpg") == "01_b.jpg"      # current file removed
    assert display.next_name([], "x") is None


def test_fade():
    assert display.fade_alphas(0, "cross") == (255, 0)
    assert display.fade_alphas(1, "cross") == (255, 255)
    assert display.fade_alphas(0.5, "black") == (0, 0)
    assert display.fade_alphas(0.25, "black")[0] in (127, 128)
    assert display.fade_alphas(1, "black") == (0, 255)
    assert display.fade_alphas(5, "cross") == (255, 255)            # clamps


def test_load_fitted():
    d = tempfile.mkdtemp()
    Image.new("RGB", (600, 900), (200, 0, 0)).save(os.path.join(d, "p.jpg"))
    Image.new("RGBA", (1920, 1080), (0, 200, 0, 255)).save(os.path.join(d, "s.png"))
    raw = display.load_fitted(os.path.join(d, "p.jpg"), 1920, 1080)
    assert len(raw) == 1920 * 1080 * 3
    img = Image.frombytes("RGB", (1920, 1080), raw)
    assert img.getpixel((10, 500)) == (0, 0, 0)                     # black bars
    assert img.getpixel((960, 500))[0] > 150                        # poster centred
    raw2 = display.load_fitted(os.path.join(d, "s.png"), 1920, 1080)
    assert Image.frombytes("RGB", (1920, 1080), raw2).getpixel((5, 5)) == (0, 200, 0)


def test_list_images():
    d = tempfile.mkdtemp()
    for n in ["b.jpg", "a.PNG", "notes.txt", ".hidden.jpg"]:
        open(os.path.join(d, n), "wb").close()
    assert display.list_images(d) == ["a.PNG", "b.jpg"]
    assert display.list_images("/nonexistent") == []


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(name, "ok")
