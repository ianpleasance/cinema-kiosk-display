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


def test_drm_ioctl_numbers_and_struct_sizes():
    import ctypes
    assert display.DRM_IOCTL_MODE_CREATE_DUMB == 0xC02064B2         # values from <drm/drm.h>
    assert display.DRM_IOCTL_MODE_MAP_DUMB == 0xC01064B3
    assert ctypes.sizeof(display.DrmModeInfo) == 68
    assert ctypes.sizeof(display.DrmModeEncoder) == 20
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        assert ctypes.sizeof(display.DrmModeRes) == 80
        assert ctypes.sizeof(display.DrmModeConnector) == 88


def test_choose_mode():
    # (width, height, refresh, interlaced, index)
    modes = [(1280, 720, 60, False, 0), (1920, 1080, 60, False, 1), (1920, 1080, 30, True, 2)]
    assert display.choose_mode(modes, 1920, 1080) == 1
    assert display.choose_mode([(1920, 1080, 30, True, 0)] + modes[:2], 1920, 1080) == 2   # skips interlaced
    assert display.choose_mode(modes, 3840, 2160) == 0               # nothing matches: first progressive
    assert display.choose_mode([(1920, 1080, 30, True, 0)], 1920, 1080) == 0


def test_blend_layers_and_pixel_order():
    bg = Image.new("RGB", (4, 2), (0, 0, 0))
    old = Image.new("RGB", (4, 2), (200, 0, 0))
    new = Image.new("RGB", (4, 2), (0, 0, 200))
    assert display.blend_layers(bg, None, None, 0, 0) is bg
    assert display.blend_layers(bg, old, new, 255, 0) is old
    assert display.blend_layers(bg, old, new, 255, 255) is new
    mid = display.blend_layers(bg, old, new, 255, 128)
    r, g, b = mid.getpixel((1, 1))
    assert 95 <= r <= 105 and g == 0 and 95 <= b <= 105
    black = display.blend_layers(bg, old, new, 128, 0)               # fading out to the background
    assert 95 <= black.getpixel((0, 0))[0] <= 105
    # the screen wants B, G, R, unused per pixel, with `pitch` bytes per row
    img = Image.new("RGB", (2, 1), (10, 20, 30))
    assert img.tobytes("raw", "BGRX", 16, 1)[:4] == bytes([30, 20, 10, 0])
    assert len(img.tobytes("raw", "BGRX", 16, 1)) == 16


def test_drm_output_writes_frames_without_a_screen():
    """Drive DrmOutput with a fake buffer to check the flip logic and frame bytes."""
    out = object.__new__(display.DrmOutput)
    out.size = (4, 2)
    out.bg_img = Image.new("RGB", out.size, (1, 2, 3))
    out.buffers = [{"fb": 1, "mem": bytearray(32), "pitch": 16}, {"fb": 2, "mem": bytearray(32), "pitch": 16}]
    out.front, out.shown = 0, False
    calls = []
    out._set_crtc = lambda fb: calls.append(("set", fb)) or 0
    class Lib:
        def drmModePageFlip(self, fd, crtc, fb, flags, data):
            calls.append(("flip", fb)); return 0
    out.lib, out.fd, out.crtc_id = Lib(), -1, 7
    out._wait_flip = lambda: None
    tex = out.make(Image.new("RGB", out.size, (50, 60, 70)).tobytes())
    out.draw(None, tex, 0, 255)                                      # first frame: sets the mode
    out.draw(None, tex, 0, 255)                                      # then flips
    assert calls == [("set", 2), ("flip", 1)]
    assert bytes(out.buffers[1]["mem"][:4]) == bytes([70, 60, 50, 0])
    assert tex["raw"] is not None                                    # converted once and kept
    out.draw(None, None, 0, 0)                                       # background only
    assert bytes(out.buffers[1]["mem"][:4]) == bytes([3, 2, 1, 0])   # buffers alternate


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(name, "ok")
