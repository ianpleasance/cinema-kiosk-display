#!/usr/bin/env python3
"""Full-screen image slideshow with fades, for a Raspberry Pi on HDMI.

Runs without a desktop. By default it draws with the CPU into plain "dumb" KMS/DRM buffers and
flips them onto the screen (DISPLAY_BACKEND=drm); this needs no GPU or OpenGL, which is what makes it
work reliably on the Pi. DISPLAY_BACKEND=sdl uses SDL/pygame instead.
Each slide is shown for HOLD_SECONDS, then faded to the next one.
Slides are the film images made by the updater plus any images you put in the
static folder. Both folders are re-read at every slide change, so a new set from
the updater, or a file you drop into the static folder, is picked up on its own.
"""
import ctypes
import ctypes.util
import fcntl
import logging
import mmap
import os
import random
import re
import select
import signal
import struct
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
DISPLAY_BACKEND = env("DISPLAY_BACKEND", "drm").lower()   # "drm" (CPU, default) or "sdl" (pygame)
if DISPLAY_BACKEND not in ("drm", "sdl"):
    print(f"WARNING: DISPLAY_BACKEND={DISPLAY_BACKEND!r} is not drm or sdl - using drm", file=sys.stderr)
    DISPLAY_BACKEND = "drm"
WANT_W = int(env_number("SCREEN_W", 1920, 16))            # screen mode to ask for (same settings the updater uses)
WANT_H = int(env_number("SCREEN_H", 1080, 16))
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
class SdlOutput:
    """Thin wrapper over pygame (DISPLAY_BACKEND=sdl)."""

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


# ------------------------------------------------- CPU / dumb-buffer output
def drm_ioctl_number(nr, size):
    """DRM_IOWR(nr, struct of `size` bytes): the same value on every Linux architecture we use."""
    return (3 << 30) | (size << 16) | (ord("d") << 8) | nr


DRM_IOCTL_MODE_CREATE_DUMB = drm_ioctl_number(0xB2, 32)
DRM_IOCTL_MODE_MAP_DUMB = drm_ioctl_number(0xB3, 16)
DRM_MODE_FLAG_INTERLACE = 0x10
DRM_MODE_PAGE_FLIP_EVENT = 1
DRM_MODE_CONNECTED = 1


class DrmModeInfo(ctypes.Structure):
    _fields_ = [("clock", ctypes.c_uint32),
                ("hdisplay", ctypes.c_uint16), ("hsync_start", ctypes.c_uint16),
                ("hsync_end", ctypes.c_uint16), ("htotal", ctypes.c_uint16), ("hskew", ctypes.c_uint16),
                ("vdisplay", ctypes.c_uint16), ("vsync_start", ctypes.c_uint16),
                ("vsync_end", ctypes.c_uint16), ("vtotal", ctypes.c_uint16), ("vscan", ctypes.c_uint16),
                ("vrefresh", ctypes.c_uint32), ("flags", ctypes.c_uint32), ("type", ctypes.c_uint32),
                ("name", ctypes.c_char * 32)]


class DrmModeRes(ctypes.Structure):
    _fields_ = [("count_fbs", ctypes.c_int), ("fbs", ctypes.POINTER(ctypes.c_uint32)),
                ("count_crtcs", ctypes.c_int), ("crtcs", ctypes.POINTER(ctypes.c_uint32)),
                ("count_connectors", ctypes.c_int), ("connectors", ctypes.POINTER(ctypes.c_uint32)),
                ("count_encoders", ctypes.c_int), ("encoders", ctypes.POINTER(ctypes.c_uint32)),
                ("min_width", ctypes.c_uint32), ("max_width", ctypes.c_uint32),
                ("min_height", ctypes.c_uint32), ("max_height", ctypes.c_uint32)]


class DrmModeConnector(ctypes.Structure):
    _fields_ = [("connector_id", ctypes.c_uint32), ("encoder_id", ctypes.c_uint32),
                ("connector_type", ctypes.c_uint32), ("connector_type_id", ctypes.c_uint32),
                ("connection", ctypes.c_uint32), ("mmWidth", ctypes.c_uint32),
                ("mmHeight", ctypes.c_uint32), ("subpixel", ctypes.c_uint32),
                ("count_modes", ctypes.c_int), ("modes", ctypes.POINTER(DrmModeInfo)),
                ("count_props", ctypes.c_int), ("props", ctypes.POINTER(ctypes.c_uint32)),
                ("prop_values", ctypes.POINTER(ctypes.c_uint64)),
                ("count_encoders", ctypes.c_int), ("encoders", ctypes.POINTER(ctypes.c_uint32))]


class DrmModeEncoder(ctypes.Structure):
    _fields_ = [("encoder_id", ctypes.c_uint32), ("encoder_type", ctypes.c_uint32),
                ("crtc_id", ctypes.c_uint32), ("possible_crtcs", ctypes.c_uint32),
                ("possible_clones", ctypes.c_uint32)]


def choose_mode(modes, want_w, want_h):
    """Pick a screen mode from (width, height, refresh_hz, interlaced, preferred_index) tuples.

    The first non-interlaced mode of the wanted size wins (the list is already in the kernel's
    preferred order); otherwise the first non-interlaced mode; otherwise the first one. Returns an index."""
    progressive = [i for i, m in enumerate(modes) if not m[3]]
    for i in progressive:
        if modes[i][0] == want_w and modes[i][1] == want_h:
            return i
    return (progressive or [0])[0]


def blend_layers(bg, old, new, old_alpha, new_alpha):
    """The frame for a fade: `old` then `new` drawn over `bg` (PIL images, alphas 0-255)."""
    frame = bg
    for img, a in ((old, old_alpha), (new, new_alpha)):
        if img is not None and a > 0:
            frame = img if a >= 255 else Image.blend(frame, img, a / 255.0)
    return frame


class DrmOutput:
    """Shows frames by writing them with the CPU into two dumb buffers and page-flipping.

    This is the same legacy KMS route that `modetest` uses, so it needs no GPU, Mesa or EGL."""

    def __init__(self):
        lib = ctypes.CDLL(ctypes.util.find_library("drm") or "libdrm.so.2", use_errno=True)
        lib.drmModeGetResources.restype = ctypes.POINTER(DrmModeRes)
        lib.drmModeGetConnector.restype = ctypes.POINTER(DrmModeConnector)
        lib.drmModeGetEncoder.restype = ctypes.POINTER(DrmModeEncoder)
        self.lib = lib
        self.fd = None
        for n in range(4):                                   # first card with a connected screen
            path = f"/dev/dri/card{n}"
            if not os.path.exists(path):
                continue
            fd = os.open(path, os.O_RDWR | os.O_CLOEXEC)
            if self._setup(fd):
                self.fd = fd
                break
            os.close(fd)
        if self.fd is None:
            raise RuntimeError("no connected screen found on /dev/dri/card0-3")
        w, h = self.size
        self.bg_img = Image.new("RGB", self.size, BACKGROUND_COLOUR)
        self.front = 0
        self._show_bytes(self._to_bytes(self.bg_img))
        log.info("Display %dx%d @ %d Hz (drm, CPU drawing)", w, h, self.refresh)

    # -- setup -------------------------------------------------------------
    def _setup(self, fd):
        lib = self.lib
        res = lib.drmModeGetResources(fd)
        if not res:
            return False
        res = res.contents
        crtcs = [res.crtcs[i] for i in range(res.count_crtcs)]
        chosen = None
        for i in range(res.count_connectors):
            conn = lib.drmModeGetConnector(fd, res.connectors[i])
            if not conn:
                continue
            c = conn.contents
            if c.connection == DRM_MODE_CONNECTED and c.count_modes > 0:
                chosen = c
                break
        if chosen is None:
            return False
        modes = [(chosen.modes[i].hdisplay, chosen.modes[i].vdisplay, chosen.modes[i].vrefresh,
                  bool(chosen.modes[i].flags & DRM_MODE_FLAG_INTERLACE), i) for i in range(chosen.count_modes)]
        self.mode = DrmModeInfo.from_buffer_copy(chosen.modes[choose_mode(modes, WANT_W, WANT_H)])
        self.connector_id = chosen.connector_id
        crtc_id = 0
        if chosen.encoder_id:
            enc = lib.drmModeGetEncoder(fd, chosen.encoder_id)
            if enc:
                crtc_id = enc.contents.crtc_id
        if not crtc_id:                                      # not lit yet: take any CRTC an encoder can use
            for j in range(chosen.count_encoders):
                enc = lib.drmModeGetEncoder(fd, chosen.encoders[j])
                if enc:
                    for k, cid in enumerate(crtcs):
                        if enc.contents.possible_crtcs & (1 << k):
                            crtc_id = cid
                            break
                if crtc_id:
                    break
        if not crtc_id:
            return False
        self.crtc_id = crtc_id
        self.size = (self.mode.hdisplay, self.mode.vdisplay)
        self.refresh = self.mode.vrefresh
        self.fd = fd
        self.buffers = [self._make_buffer(fd) for _ in range(2)]
        return True

    def _make_buffer(self, fd):
        w, h = self.size
        req = bytearray(struct.pack("IIIIIIQ", h, w, 32, 0, 0, 0, 0))
        fcntl.ioctl(fd, DRM_IOCTL_MODE_CREATE_DUMB, req)
        _h, _w, _bpp, _flags, handle, pitch, size = struct.unpack("IIIIIIQ", bytes(req))
        fb_id = ctypes.c_uint32(0)
        if self.lib.drmModeAddFB(fd, w, h, 24, 32, pitch, handle, ctypes.byref(fb_id)):
            raise RuntimeError("drmModeAddFB failed")
        mreq = bytearray(struct.pack("IIQ", handle, 0, 0))
        fcntl.ioctl(fd, DRM_IOCTL_MODE_MAP_DUMB, mreq)
        offset = struct.unpack("IIQ", bytes(mreq))[2]
        mem = mmap.mmap(fd, size, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=offset)
        return {"fb": fb_id.value, "mem": mem, "pitch": pitch}

    # -- drawing -----------------------------------------------------------
    def _to_bytes(self, img):
        """Pixels as the screen wants them: B, G, R, unused per pixel, `pitch` bytes per row."""
        return img.tobytes("raw", "BGRX", self.buffers[0]["pitch"], 1)

    def _set_crtc(self, fb):
        conn = (ctypes.c_uint32 * 1)(self.connector_id)
        return self.lib.drmModeSetCrtc(self.fd, self.crtc_id, fb, 0, 0, conn, 1, ctypes.byref(self.mode))

    def _show_bytes(self, data):
        """Write a frame into the hidden buffer and flip to it."""
        back = 1 - self.front
        buf = self.buffers[back]
        buf["mem"][:len(data)] = data
        if not self.shown:
            if self._set_crtc(buf["fb"]):
                raise RuntimeError("drmModeSetCrtc failed (is another program using the screen?)")
            self.shown = True
        elif self.lib.drmModePageFlip(self.fd, self.crtc_id, buf["fb"], DRM_MODE_PAGE_FLIP_EVENT, None) == 0:
            self._wait_flip()
        else:
            self._set_crtc(buf["fb"])                        # flip refused: set it directly (may tear)
        self.front = back

    shown = False

    def _wait_flip(self):
        if select.select([self.fd], [], [], 0.5)[0]:
            try:
                os.read(self.fd, 4096)                       # the "flip finished" event
            except OSError:
                pass

    def make(self, rgb_bytes):
        img = Image.frombytes("RGB", self.size, rgb_bytes)
        return {"img": img, "raw": None}

    def draw(self, old, new, old_alpha, new_alpha):
        frame = blend_layers(self.bg_img, old["img"] if old else None, new["img"] if new else None,
                             old_alpha, new_alpha)
        owner = new if (new and frame is new["img"]) else old if (old and frame is old["img"]) else None
        if owner is not None:                                # a whole slide: convert once, reuse
            if owner["raw"] is None:
                owner["raw"] = self._to_bytes(frame)
            self._show_bytes(owner["raw"])
        else:
            self._show_bytes(self._to_bytes(frame))

    def pump(self):
        return True


# --------------------------------------------------------------------- main
def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        stream=sys.stdout)
    log.info("Empire kiosk display v%s starting", __version__)
    running = {"on": True}
    signal.signal(signal.SIGTERM, lambda *_: running.update(on=False))

    out = None
    if DISPLAY_BACKEND == "drm":
        try:
            out = DrmOutput()
        except Exception as e:
            log.error("DRM output failed (%s) - trying SDL", e)
    if out is None:
        out = SdlOutput()
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
