"""The optional slideshow video: modes, fades, and only rebuilding when something changed."""
import json
import os
import shutil
import subprocess
import sys
import tempfile

from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "updater"))
import updater  # noqa: E402

HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def setup(n_films=3, n_static=0):
    data, video, static = tempfile.mkdtemp(), tempfile.mkdtemp(), tempfile.mkdtemp()
    gen = os.path.join(data, "gen-1")
    os.makedirs(gen)
    for i in range(n_films):
        Image.new("RGB", (640, 360), (40 * i, 80, 200)).save(os.path.join(gen, f"{i+1:02d}_f{i}_b_info.jpg"))
    os.symlink("gen-1", os.path.join(data, "current"))
    for i in range(n_static):
        Image.new("RGB", (300, 300), (200, 20 * i, 20)).save(os.path.join(static, f"s{i}.png"))
    updater.STATIC_DIR = static
    updater.SCREEN_W, updater.SCREEN_H = 320, 240
    updater.HOLD_SECONDS, updater.FADE_SECONDS, updater.FADE_MODE = 0.8, 0.4, "cross"
    return data, video, static


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", path], capture_output=True, text=True).stdout
    return float(out)


def size(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height", "-of", "csv=p=0", path], capture_output=True, text=True).stdout
    return tuple(int(x) for x in out.strip().split(","))


def test_playlist_matches_display():
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "display"))
    import display
    data, _, static = setup(5, 2)
    cur = os.path.join(data, "current")
    for pos in ("after", "before", "spread"):
        assert updater.build_playlist(cur, static, pos) == display.build_playlist(cur, static, pos), pos
    print("test_playlist_matches_display ok")


def test_modes_and_durations():
    if not HAVE_FFMPEG:
        print("test_modes_and_durations skipped (no ffmpeg)"); return
    for mode, expect in (("none", []), ("plain", ["slideshow.mp4"]), ("fade", ["slideshow-fade.mp4"]),
                         ("both", ["slideshow.mp4", "slideshow-fade.mp4"])):
        data, video, _ = setup(3, 1)                         # 3 film slides + 1 static = 4 slides
        built = updater.update_videos(data, video, mode)
        assert built == expect, (mode, built)
        files = sorted(f for f in os.listdir(video) if not f.startswith("."))
        assert files == sorted(expect), (mode, files)
        if "slideshow.mp4" in expect:
            assert abs(duration(os.path.join(video, "slideshow.mp4")) - 4 * 0.8) < 0.15
            assert size(os.path.join(video, "slideshow.mp4")) == (320, 240)
        if "slideshow-fade.mp4" in expect:
            assert abs(duration(os.path.join(video, "slideshow-fade.mp4")) - (4 * 0.8 + 3 * 0.4)) < 0.2
    print("test_modes_and_durations ok")


def test_only_rebuilds_when_something_changed():
    if not HAVE_FFMPEG:
        print("test_only_rebuilds skipped (no ffmpeg)"); return
    data, video, static = setup(2, 0)
    calls = []
    real = updater.run_ffmpeg
    updater.run_ffmpeg = lambda a: (calls.append(a), real(a))[1]
    try:
        assert len(updater.update_videos(data, video, "both")) == 2
        n = len(calls)
        assert updater.update_videos(data, video, "both") == [] and len(calls) == n    # nothing changed
        updater.FADE_SECONDS = 0.2                                                      # fade-only setting
        assert updater.update_videos(data, video, "both") == ["slideshow-fade.mp4"]
        updater.HOLD_SECONDS = 1.0                                                      # affects both
        assert sorted(updater.update_videos(data, video, "both")) == ["slideshow-fade.mp4", "slideshow.mp4"]
        Image.new("RGB", (100, 100), (1, 2, 3)).save(os.path.join(static, "new.png"))   # slide list changed
        assert len(updater.update_videos(data, video, "both")) == 2
        gen = os.path.join(data, "gen-1")                                               # slide content changed
        Image.new("RGB", (640, 360), (250, 250, 0)).save(os.path.join(gen, "01_f0_b_info.jpg"))
        assert len(updater.update_videos(data, video, "both")) == 2
        os.remove(os.path.join(video, "slideshow.mp4"))                                 # file went missing
        assert updater.update_videos(data, video, "both") == ["slideshow.mp4"]
        # switching mode removes the video that is no longer wanted, keeps the other untouched
        assert updater.update_videos(data, video, "plain") == []
        assert not os.path.exists(os.path.join(video, "slideshow-fade.mp4"))
        assert os.path.exists(os.path.join(video, "slideshow.mp4"))
        assert updater.update_videos(data, video, "none") == []
        assert [f for f in os.listdir(video) if not f.startswith(".")] == []
        assert not [d for d in os.listdir(video) if d.startswith(".build-")]
    finally:
        updater.run_ffmpeg = real
    print("test_only_rebuilds_when_something_changed ok")


def test_black_fade_and_zero_fade():
    if not HAVE_FFMPEG:
        print("test_black_fade skipped (no ffmpeg)"); return
    data, video, _ = setup(2, 0)
    updater.FADE_MODE = "black"
    updater.update_videos(data, video, "fade")
    assert abs(duration(os.path.join(video, "slideshow-fade.mp4")) - (2 * 0.8 + 0.4)) < 0.2
    data, video, _ = setup(2, 0)
    updater.FADE_SECONDS = 0
    updater.update_videos(data, video, "fade")
    assert abs(duration(os.path.join(video, "slideshow-fade.mp4")) - 1.6) < 0.2
    print("test_black_fade_and_zero_fade ok")


def test_fade_really_fades():
    if not HAVE_FFMPEG:
        print("test_fade_really_fades skipped (no ffmpeg)"); return

    def brightness(path, t):
        out = os.path.join(tempfile.mkdtemp(), "f.png")
        subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", path, "-frames:v", "1", out], check=True)
        return Image.open(out).convert("L").resize((1, 1)).getpixel((0, 0))   # includes the letterbox bars

    def make(mode, second):
        data, video, _ = setup(2, 0)
        gen = os.path.join(data, "gen-1")
        Image.new("RGB", (640, 360), (255, 255, 255)).save(os.path.join(gen, "01_f0_b_info.jpg"))
        Image.new("RGB", (640, 360), second).save(os.path.join(gen, "02_f1_b_info.jpg"))
        updater.FADE_MODE, updater.FADE_SECONDS, updater.HOLD_SECONDS = mode, 1.0, 1.0
        updater.update_videos(data, video, "fade")
        return os.path.join(video, "slideshow-fade.mp4")

    v = make("cross", (0, 0, 0))                         # white -> black
    full, mid, last = brightness(v, 0.5), brightness(v, 1.5), brightness(v, 2.5)
    assert full > 150 and last < 10 and last < mid < full, (full, mid, last)     # in between mid-fade
    v = make("black", (255, 255, 255))                   # white -> white, but through black
    dark = min(brightness(v, 1.0 + i / 10) for i in range(0, 11))
    assert brightness(v, 0.5) > 150 and brightness(v, 2.5) > 150 and dark < 20, dark
    print("test_fade_really_fades ok")


def test_failures_never_break_updates():
    data, video, _ = setup(2, 0)
    real = updater.run_ffmpeg
    updater.VIDEO_DIR, saved = video, updater.VIDEO_DIR
    updater.VIDEO_MODE, saved_mode = "plain", updater.VIDEO_MODE
    def boom(args):
        raise RuntimeError("ffmpeg failed: nope")
    updater.run_ffmpeg = boom
    updater.DATA_DIR, saved_data = data, updater.DATA_DIR
    try:
        updater.make_videos()                              # logged, not raised
        assert os.path.exists(os.path.join(data, "current")) and updater.VIDEO_MODE == "plain"
        assert not [f for f in os.listdir(video) if not f.startswith(".")]
        assert not [d for d in os.listdir(video) if d.startswith(".build-")]     # no litter
    finally:
        updater.run_ffmpeg, updater.VIDEO_DIR, updater.VIDEO_MODE, updater.DATA_DIR = real, saved, saved_mode, saved_data
    print("test_failures_never_break_updates ok")


if __name__ == "__main__":
    test_playlist_matches_display()
    test_modes_and_durations()
    test_only_rebuilds_when_something_changed()
    test_black_fade_and_zero_fade()
    test_fade_really_fades()
    test_failures_never_break_updates()
