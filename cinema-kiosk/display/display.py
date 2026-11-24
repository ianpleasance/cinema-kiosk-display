#!/usr/bin/env python3
"""Full-screen image slideshow with fades, for a Raspberry Pi on HDMI.

Runs without a desktop: SDL talks straight to the display through KMS/DRM.
Each slide is shown for HOLD_SECONDS, then faded to the next one.
The folder is re-read at every slide change, so when the updater swaps in a
new set of images the display picks it up on its own.
"""
import logging
import os
import signal
import sys
import time

from PIL import Image

IMAGE_DIR = os.environ.get("IMAGE_DIR", "/data/current")
HOLD_SECONDS = float(os.environ.get("HOLD_SECONDS", "10"))
FADE_SECONDS = float(os.environ.get("FADE_SECONDS", "1.0"))
FADE_MODE = os.environ.get("FADE_MODE", "cross")        # "cross" or "black"
SHUFFLE = os.environ.get("SHUFFLE", "0") == "1"
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
    return sorted(names)


def next_name(names, current):
    """Name following `current` in `names` (wrapping); first name if current is gone."""
    if not names:
        return None
    if current is None:
        return names[0]
    for n in names:
        if n > current:
            return n
    return names[0]


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


def load_fitted(path, w, h):
    """Decode an image and fit it inside w x h on black. Returns raw RGB bytes."""
    img = Image.open(path)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (0, 0, 0))
        bg.paste(img, mask=img.split()[-1])
        img = bg
    else:
        img = img.convert("RGB")
    if img.size != (w, h):
        scale = min(w / img.width, h / img.height)
        size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
        img = img.resize(size, Image.LANCZOS)
        canvas = Image.new("RGB", (w, h), (0, 0, 0))
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
            self.renderer.draw_color = (0, 0, 0, 255)
            self.renderer.clear()
            for img, a in ((old, old_alpha), (new, new_alpha)):
                if img is not None and a > 0:
                    img.alpha = a
                    img.draw()
            self.renderer.present()
        else:
            self.screen.fill((0, 0, 0))
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
    running = {"on": True}
    signal.signal(signal.SIGTERM, lambda *_: running.update(on=False))

    out = Output()
    w, h = out.size
    current_name, current_tex = None, None

    def load(name):
        try:
            return out.make(load_fitted(os.path.join(IMAGE_DIR, name), w, h))
        except Exception as e:
            log.warning("could not load %s: %s", name, e)
            return None

    while running["on"] and out.pump():
        names = list_images(IMAGE_DIR)
        if not names:
            out.draw(None, None, 0, 0)               # black while waiting for first update
            time.sleep(EMPTY_RETRY_SECONDS)
            continue

        if SHUFFLE and current_name is not None:
            import random
            name = random.choice([n for n in names if n != current_name] or names)
        else:
            name = next_name(names, current_name)
        new_tex = load(name)
        if new_tex is None:
            current_name = name                      # skip unreadable file
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
        current_name, current_tex = name, new_tex
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
