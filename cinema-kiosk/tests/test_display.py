"""Tests for the display's pure logic (no pygame / screen needed)."""
import io
import os
import sys
import tempfile

from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "display"))
import display  # noqa: E402


def _touch(folder, names):
    os.makedirs(folder, exist_ok=True)
    for n in names:
        Image.new("RGB", (4, 4)).save(os.path.join(folder, n))


def test_build_playlist():
    root = tempfile.mkdtemp()
    films, statics = os.path.join(root, "films"), os.path.join(root, "static")
    _touch(films, ["01_a.png", "01_b.png", "02_a.png", "02_b.png", "03_a.png", "03_b.png"])
    _touch(statics, ["10_rules.png", "Offers.PNG"])
    open(os.path.join(statics, "README.txt"), "w").close()               # ignored
    names = lambda pl: [os.path.basename(p) for p in pl]                 # noqa: E731

    assert names(display.build_playlist(films, statics, "after")) == \
        ["01_a.png", "01_b.png", "02_a.png", "02_b.png", "03_a.png", "03_b.png", "10_rules.png", "Offers.PNG"]
    assert names(display.build_playlist(films, statics, "before")) == \
        ["10_rules.png", "Offers.PNG", "01_a.png", "01_b.png", "02_a.png", "02_b.png", "03_a.png", "03_b.png"]
    # spread: 6 films, 2 statics -> after film 2 and after film 4
    assert names(display.build_playlist(films, statics, "spread")) == \
        ["01_a.png", "01_b.png", "10_rules.png", "02_a.png", "02_b.png", "Offers.PNG", "03_a.png", "03_b.png"]
    # missing / empty folders
    assert names(display.build_playlist(films, "/nonexistent", "after")) == \
        ["01_a.png", "01_b.png", "02_a.png", "02_b.png", "03_a.png", "03_b.png"]
    assert names(display.build_playlist("/nonexistent", statics, "spread")) == ["10_rules.png", "Offers.PNG"]
    assert display.build_playlist("/nonexistent", "/nonexistent2", "after") == []
    # a single static with spread lands in the middle; many statics never lose items
    one = tempfile.mkdtemp(); _touch(one, ["x.png"])
    assert names(display.build_playlist(films, one, "spread")).index("x.png") == 3
    many = tempfile.mkdtemp(); _touch(many, [f"s{i}.png" for i in range(9)])
    assert len(display.build_playlist(films, many, "spread")) == 15


def test_pick_next():
    import random
    pl = ["a", "b", "c"]
    assert display.pick_next(pl, None) == "a"
    assert display.pick_next(pl, "a") == "b"
    assert display.pick_next(pl, "c") == "a"                  # wraps
    assert display.pick_next(pl, "gone") == "a"               # current vanished -> top
    assert display.pick_next([], "a") is None
    rng = random.Random(1)
    picks = {display.pick_next(pl, "b", True, rng) for _ in range(50)}
    assert picks == {"a", "c"}                                # random, never the same slide twice
    assert display.pick_next(["only"], "only", True) == "only"


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


def test_load_fitted_honours_photo_rotation():
    import tempfile
    from PIL import Image
    d = tempfile.mkdtemp()
    img = Image.new("RGB", (200, 100), (255, 0, 0))                 # stored landscape...
    exif = Image.Exif()
    exif[0x0112] = 6                                                 # ...but flagged "rotate 90 clockwise"
    path = os.path.join(d, "phone.jpg")
    img.save(path, exif=exif)
    raw = display.load_fitted(path, 100, 200)                        # so it is really portrait: fills 100x200
    assert raw[0] > 200 and raw[2] < 60, raw[:3]                    # red at the very corner: no black bars
    print("test_load_fitted_honours_photo_rotation ok")


def test_background_colour():
    d = tempfile.mkdtemp()
    Image.new("RGBA", (600, 900), (255, 0, 0, 0)).save(os.path.join(d, "t.png"))      # fully transparent
    raw = display.load_fitted(os.path.join(d, "t.png"), 1920, 1080, bg=(10, 20, 90))
    img = Image.frombytes("RGB", (1920, 1080), raw)
    assert img.getpixel((5, 500)) == (10, 20, 90)                    # letterbox bar
    assert img.getpixel((960, 500)) == (10, 20, 90)                  # transparency flattened onto it
    raw = display.load_fitted(os.path.join(d, "t.png"), 1920, 1080)  # default is the setting (black)
    assert Image.frombytes("RGB", (1920, 1080), raw).getpixel((5, 500)) == display.BACKGROUND_COLOUR


def test_list_images():
    d = tempfile.mkdtemp()
    for n in ["b.jpg", "a.PNG", "notes.txt", ".hidden.jpg"]:
        open(os.path.join(d, n), "wb").close()
    assert display.list_images(d) == ["a.PNG", "b.jpg"]
    open(os.path.join(d, "B2.jpg"), "wb").close()
    assert display.list_images(d) == ["a.PNG", "b.jpg", "B2.jpg"]      # case-insensitive order
    assert display.list_images("/nonexistent") == []


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(name, "ok")
