#!/usr/bin/env python3
"""Full-screen image slideshow with fades, for a Raspberry Pi on HDMI.

Runs without a desktop: SDL talks straight to the display through KMS/DRM.
Each slide is shown for HOLD_SECONDS, then faded to the next one.
Slides are the film images made by the updater plus any images you put in the
static folder. Both folders are re-read at every slide change, so a new set from
the updater, or a file you drop into the static folder, is picked up on its own.
"""
import logging
import os
import random
import re
import signal
import sys
import time

from PIL import Image, ImageOps


__version__ = "1.0.0"          # keep in step with the VERSION file (a test checks this)


def env(name, default):
    """Setting from the environment (.env file); blank or missing falls back to the default."""
    value = os.environ.get(name, "").strip().strip("\"'").strip()   # tolerate quotes / CRLF
    return value if value else default


def env_bool(name, default):
    return env(name, "1" if default else "0").lower() in ("1", "true", "yes", "on")


def env_number(name, default, lo=None, hi=None):
    """Number setting checked against lo..hi; missing/blank/invalid/out of range -> default."""
    raw = env(name, "")
    if not raw:
        return default
    try:
        value = float(raw)
        if isinstance(default, int):
            value = int(value)
    except ValueError:
        print(f"WARNING: {name}={raw!r} is not a number - using {default}", file=sys.stderr)
        return default
    if (lo is not None and value < lo) or (hi is not None and value > hi):
        print(f"WARNING: {name}={raw!r} is outside {lo}..{hi} - using {default}", file=sys.stderr)
        return default
    return value


def env_colour(name, default_hex):
    """Colour setting as hex (FFFFFF or FFF; a leading # is tolerated) -> (r, g, b)."""
    raw = env(name, default_hex).lstrip("#")
    if re.fullmatch(r"[0-9a-fA-F]{3}", raw):
        raw = "".join(c * 2 for c in raw)
    if not re.fullmatch(r"[0-9a-fA-F]{6}", raw):
        print(f"WARNING: {name}={raw!r} is not a hex colour like FFFFFF - using {default_hex}",
              file=sys.stderr)
        raw = default_hex
    return tuple(int(raw[i:i + 2], 16) for i in (0, 2, 4))


IMAGE_DIR = env("IMAGE_DIR", "/data/current")           # film slides from the updater
STATIC_DIR = env("STATIC_DIR", "/static")                # your own images, mounted from ./static
STATIC_POSITION = env("STATIC_POSITION", "after").lower()   # after | before | spread
if STATIC_POSITION not in ("after", "before", "spread"):
    print(f"WARNING: STATIC_POSITION={STATIC_POSITION!r} is not after/before/spread - using after",
          file=sys.stderr)
    STATIC_POSITION = "after"
HOLD_SECONDS = env_number("HOLD_SECONDS", 10.0, 0.5)
FADE_SECONDS = env_number("FADE_SECONDS", 1.0, 0.0)
BACKGROUND_COLOUR = env_colour("BACKGROUND_COLOUR", "000000")   # edges around images, fade-to colour
FADE_MODE = env("FADE_MODE", "cross").lower()        # "cross" or "black"
if FADE_MODE not in ("cross", "black"):
    print(f"WARNING: FADE_MODE={FADE_MODE!r} is not cross or black - using cross", file=sys.stderr)
    FADE_MODE = "cross"
SHUFFLE = env_bool("SHUFFLE", False)
EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")
EMPTY_RETRY_SECONDS = 5

log = logging.getLogger("display")


# ---------------------------------------------------------------- pure logic
def list_images(folder):
    try:
        names = [n for n in os.listdir(folder)
                 if n.lower().endswith(EXTS) and not n.startswith(".")]
    except OSError:
        return []
    return sorted(names, key=str.lower)


def build_playlist(film_dir, static_dir, position="after"):
    """Full paths of every slide to show, in order.

    Film slides come from the updater's folder; static images from your own folder
    (both sorted by file name). `position` says where the static ones go:
    after / before the film slides, or spread evenly through them."""
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
        for k, s in enumerate(statics):
            target = round((k + 1) * len(films) / (len(statics) + 1))
            out.extend(films[taken:target])
            taken = target
            out.append(s)
        return out + films[taken:]
    return films + statics


def pick_next(playlist, current, shuffle=False, rng=random):
    """The slide after `current` (wrapping), or a random other one when shuffling.
    If `current` has disappeared (e.g. the updater swapped in a new set) start again at the top."""
    if not playlist:
        return None
    if shuffle:
        return rng.choice([p for p in playlist if p != current] or playlist)
    if current in playlist:
        return playlist[(playlist.index(current) + 1) % len(playlist)]
    return playlist[0]


def fade_alphas(t, mode="cross"):
    """For transition progress t in [0,1] return (old_alpha, new_alpha) 0-255.

    cross: new image fades in over the fully visible old one (no dip to black).
    black: old fades out to black, then new fades in from black.
    """
    t = min(1.0, max(0.0, t))
    if mode == "black":
        if t < 0.5:
            return round(255 * (1 - 2 * t)), 0
        return 0, round(255 * (2 * t - 1))
    return 255, round(255 * t)


def load_fitted(path, w, h, bg=None):
    """Decode an image and fit it inside w x h on the background colour. Returns raw RGB bytes."""
    bg = BACKGROUND_COLOUR if bg is None else bg
    img = ImageOps.exif_transpose(Image.open(path))      # phone photos: honour the rotation flag
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        flat = Image.new("RGB", img.size, bg)
        flat.paste(img, mask=img.split()[-1])
        img = flat
    else:
        img = img.convert("RGB")
    if img.size != (w, h):
        scale = min(w / img.width, h / img.height)
        size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
        img = img.resize(size, Image.LANCZOS)
        canvas = Image.new("RGB", (w, h), bg)
        canvas.paste(img, ((w - size[0]) // 2, (h - size[1]) // 2))
        img = canvas
    return img.tobytes()


# ------------------------------------------------------------------- output
class Output:
    """Thin wrapper over pygame so the rest of the code doesn't care how we draw."""

    def __init__(self):
        import pygame
        self.pg = pygame
        pygame.init()
        pygame.mouse.set_visible(False)
        try:
            from pygame._sdl2 import video
            info = pygame.display.Info()
            size = (info.current_w, info.current_h)
            self.window = video.Window("kiosk", size, fullscreen=True)
            self.renderer = video.Renderer(self.window, vsync=True)
            self.size = self.window.size
            self.Texture = video.Texture
            self.gpu = True
        except Exception as e:                       # old pygame / no GPU renderer
            log.warning("GPU renderer unavailable (%s) - using software blit", e)
            self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
            self.size = self.screen.get_size()
            self.gpu = False
        log.info("Display %dx%d (%s)", *self.size, "gpu" if self.gpu else "software")

    def make(self, rgb_bytes):
        surf = self.pg.image.frombuffer(rgb_bytes, self.size, "RGB")
        if self.gpu:
            tex = self.Texture.from_surface(self.renderer, surf)
            tex.blend_mode = 1                       # SDL_BLENDMODE_BLEND
            return tex
        return surf.convert()

    def draw(self, old, new, old_alpha, new_alpha):
        if self.gpu:
            self.renderer.draw_color = (*BACKGROUND_COLOUR, 255)
            self.renderer.clear()
            for img, a in ((old, old_alpha), (new, new_alpha)):
                if img is not None and a > 0:
                    img.alpha = a
                    img.draw()
            self.renderer.present()
        else:
            self.screen.fill(BACKGROUND_COLOUR)
            for img, a in ((old, old_alpha), (new, new_alpha)):
                if img is not None and a > 0:
                    img.set_alpha(a)
                    self.screen.blit(img, (0, 0))
            self.pg.display.flip()

    def pump(self):
        for e in self.pg.event.get():
            if e.type == self.pg.QUIT or (e.type == self.pg.KEYDOWN and e.key == self.pg.K_ESCAPE):
                return False
        return True


# --------------------------------------------------------------------- main
def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        stream=sys.stdout)
    log.info("Empire kiosk display v%s starting", __version__)
    running = {"on": True}
    signal.signal(signal.SIGTERM, lambda *_: running.update(on=False))

    out = Output()
    w, h = out.size
    current_path, current_tex = None, None

    def load(path):
        try:
            return out.make(load_fitted(path, w, h))
        except Exception as e:
            log.warning("could not load %s: %s", path, e)
            return None

    while running["on"] and out.pump():
        playlist = build_playlist(IMAGE_DIR, STATIC_DIR, STATIC_POSITION)
        if not playlist:
            out.draw(None, None, 0, 0)               # black while waiting for first update
            time.sleep(EMPTY_RETRY_SECONDS)
            continue

        path = pick_next(playlist, current_path, SHUFFLE)
        new_tex = load(path)
        if new_tex is None:
            current_path = path                      # skip unreadable file
            time.sleep(0.1)
            continue

        # fade from the previous slide (or from black on first run)
        start = time.monotonic()
        while running["on"]:
            t = (time.monotonic() - start) / max(FADE_SECONDS, 0.001)
            oa, na = fade_alphas(t, FADE_MODE)
            out.draw(current_tex, new_tex, oa, na)
            if t >= 1.0 or not out.pump():
                break
            time.sleep(0.005)
        current_path, current_tex = path, new_tex
        out.draw(None, current_tex, 0, 255)

        # hold, keeping the event loop alive
        end = time.monotonic() + HOLD_SECONDS
        while running["on"] and time.monotonic() < end:
            if not out.pump():
                running["on"] = False
            time.sleep(0.1)

    log.info("exiting")


if __name__ == "__main__":
    main()
