"""rewind.py - rewind Earth's plates on a plain globe and save it as a video.

    python rewind.py                                   # 0 -> 200 Ma at 10 Myr per second
    python rewind.py --end 600 --pin London --pin Beijing --follow London
    python rewind.py --still 250 --pin "40.7,-74.0,Home"   # one PNG, quick check
    python rewind.py --model Cao2024 --end 1800 --rate 60

Every frame is the model, read at that age: coastlines from pygplates.reconstruct, plate boundaries
from pygplates.resolve_topologies, pins rotated with the model's own rotations. Nothing is drawn by hand.
"""
import argparse
import math
import multiprocessing as mp
import os
import shutil
import subprocess

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from plates import Model, parse_place

W, H = 1920, 1080
SS = 2                      # draw at 2x and shrink: smooth edges
TEX_W, TEX_H = 4096, 2048   # land is drawn flat (lat/lon) first, then wrapped onto the sphere
SPACE = (20, 22, 30)
OCEAN = (52, 98, 150)
LAND = (214, 200, 170)
COAST = (60, 50, 40)
BOUND = (200, 60, 50)
PIN = (255, 255, 255)
TEXT = (235, 235, 235)


def font(px):
    try:
        return ImageFont.load_default(size=px)        # Pillow 10.1+
    except TypeError:
        return ImageFont.load_default()


# ---- land texture (flat lat/lon map) ----------------------------------------------------------
def land_mask(polys):
    """Fill every coastline polygon onto a flat lat/lon map. Handles the date line and the poles."""
    img = Image.new("L", (TEX_W, TEX_H), 0)
    d = ImageDraw.Draw(img)
    for p in polys:
        if len(p) < 3:
            continue
        lat, lon = p[:, 0], np.degrees(np.unwrap(np.radians(p[:, 1])))
        x = (lon + 180) / 360 * TEX_W
        y = (90 - lat) / 180 * TEX_H
        pts = list(zip(x, y))
        if abs(lon[-1] - lon[0]) > 180:                # the polygon wraps around a pole: close it along the pole
            py = 0 if lat.mean() > 0 else TEX_H
            pts += [(x[-1], py), (x[0], py)]
        for shift in (-TEX_W, 0, TEX_W):
            d.polygon([(a + shift, b) for a, b in pts], fill=255)
    return np.asarray(img) > 127


# ---- the globe ------------------------------------------------------------------------------
def view_matrix(lon0, lat0):
    """Rows: screen right, screen up, toward the viewer (world xyz)."""
    lo, la = math.radians(lon0), math.radians(lat0)
    f = np.array([math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo), math.sin(la)])
    r = np.cross([0, 0, 1.0], f)
    r /= np.linalg.norm(r)
    return np.stack([r, np.cross(f, r), f])


def to_xyz(lat, lon):
    la, lo = np.radians(lat), np.radians(lon)
    return np.stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)], -1)


class Globe:
    def __init__(self, cx, cy, radius):
        self.cx, self.cy, self.R = cx, cy, radius
        n = int(radius * 2) + 2
        yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
        self.x0, self.y0 = int(cx - n / 2), int(cy - n / 2)
        nx = (xx + self.x0 + .5 - cx) / radius
        ny = -(yy + self.y0 + .5 - cy) / radius
        r2 = nx * nx + ny * ny
        self.inside = r2 < 1
        self.N = np.stack([nx, ny, np.sqrt(np.clip(1 - r2, 0, 1))], -1)[self.inside]
        self.n = n

    def project(self, lat, lon, V):
        """lat/lon arrays -> screen x, y and 'facing us' (z > 0)."""
        P = to_xyz(lat, lon) @ V.T
        return self.cx + P[:, 0] * self.R, self.cy - P[:, 1] * self.R, P[:, 2]

    def draw(self, img, mask, V):
        world = self.N @ V                             # each globe pixel -> a point on Earth
        lat = np.degrees(np.arcsin(np.clip(world[:, 2], -1, 1)))
        lon = np.degrees(np.arctan2(world[:, 1], world[:, 0]))
        tx = ((lon + 180) / 360 * TEX_W).astype(int) % TEX_W
        ty = np.clip(((90 - lat) / 180 * TEX_H).astype(int), 0, TEX_H - 1)
        land = np.zeros((self.n, self.n), bool)
        land[self.inside] = mask[ty, tx]
        rgb = np.zeros((self.n, self.n, 3), np.uint8)
        rgb[self.inside] = OCEAN
        rgb[land] = LAND
        grow = np.asarray(Image.fromarray(land.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(3))) > 0
        rgb[grow & ~land & self.inside] = COAST        # a thin coastline
        alpha = Image.fromarray(self.inside.astype(np.uint8) * 255)
        img.paste(Image.fromarray(rgb), (self.x0, self.y0), alpha)
        ImageDraw.Draw(img).ellipse([self.cx - self.R, self.cy - self.R, self.cx + self.R, self.cy + self.R],
                                    outline=(0, 0, 0), width=SS * 2)

    def lines(self, img, polylines, V, color, width):
        d = ImageDraw.Draw(img)
        for p in polylines:
            x, y, z = self.project(p[:, 0], p[:, 1], V)
            run = []
            for a, b, c in zip(x, y, z):
                if c > 0:
                    run.append((a, b))
                else:
                    if len(run) > 1:
                        d.line(run, fill=color, width=width)
                    run = []
            if len(run) > 1:
                d.line(run, fill=color, width=width)

    def pin(self, img, lat, lon, V, label, f):
        x, y, z = self.project(np.array([lat]), np.array([lon]), V)
        if z[0] <= 0:
            return
        x, y, s = x[0], y[0], 7 * SS
        d = ImageDraw.Draw(img)
        d.ellipse([x - s, y - s, x + s, y + s], fill=PIN, outline=(0, 0, 0), width=SS * 2)
        d.text((x + s * 1.8, y), label, font=f, fill=TEXT, anchor="lm", stroke_width=SS * 2, stroke_fill=(0, 0, 0))


# ---- one frame ------------------------------------------------------------------------------
def frame(model, t, view, pins, show_bounds, g, fonts):
    img = Image.new("RGB", (W * SS, H * SS), SPACE)
    V = view_matrix(*view)
    g.draw(img, land_mask(model.coastlines_at(t)), V)
    if show_bounds:
        try:
            g.lines(img, model.boundaries_at(t), V, BOUND, SS * 2)
        except Exception as e:                         # a model with no boundaries at this age: carry on
            print(f"  boundaries at {t:.0f} Ma skipped: {e}")
    for label, la, lo, plate, ground_age in pins:
        if t <= ground_age:                            # the ground under the pin existed then
            plat, plon = model.point_at(la, lo, t, plate)
            g.pin(img, plat, plon, V, label, fonts["pin"])
    d = ImageDraw.Draw(img)
    d.text((60 * SS, 50 * SS), f"{t:,.0f}", font=fonts["big"], fill=TEXT)
    d.text((60 * SS, 150 * SS), "million years ago", font=fonts["small"], fill=TEXT)
    d.text((60 * SS, (H - 50) * SS), f"Plate model: {model.credit}", font=fonts["tiny"], fill=(160, 160, 160))
    return img.resize((W, H), Image.LANCZOS)


_WORKER = {}


def _init(model_name, data_dir, pins, bounds, fdir):
    _WORKER.update(model=Model(model_name, data_dir), pins=pins, bounds=bounds, fdir=fdir,
                   globe=Globe(W * SS * 0.58, H * SS * 0.5, H * SS * 0.42),
                   fonts={"big": font(96 * SS), "small": font(32 * SS), "tiny": font(18 * SS), "pin": font(22 * SS)})


def _render(job):
    i, t, view = job
    w = _WORKER
    frame(w["model"], t, view, w["pins"], w["bounds"], w["globe"], w["fonts"]).save(
        os.path.join(w["fdir"], f"{i:05d}.png"))


def ease_view(prev, target, k=0.08):
    """Turn the globe smoothly toward a target (lon, lat) instead of jumping."""
    if prev is None:
        return target
    dlon = (target[0] - prev[0] + 180) % 360 - 180
    return prev[0] + dlon * k, prev[1] + (target[1] - prev[1]) * k


def main():
    ap = argparse.ArgumentParser(description="Rewind Earth's plates on a plain globe.")
    ap.add_argument("--model", default="Muller2025", help="Muller2025 (default) or Cao2024")
    ap.add_argument("--data-dir", default="data", help="where the model files live / get downloaded")
    ap.add_argument("--start", type=float, default=0, help="first age in Ma (millions of years ago)")
    ap.add_argument("--end", type=float, default=200, help="last age in Ma (up to 1800)")
    ap.add_argument("--rate", type=float, default=10, help="million years per second of video")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--pin", action="append", default=[], help='city name, "lat,lon" or "lat,lon,Label"; repeat for more')
    ap.add_argument("--follow", help="keep this pin facing you (its label or city name)")
    ap.add_argument("--lon", type=float, default=0, help="view longitude when not following")
    ap.add_argument("--lat", type=float, default=20, help="view latitude when not following")
    ap.add_argument("--no-boundaries", action="store_true", help="skip plate boundaries (faster)")
    ap.add_argument("--still", type=float, help="render one PNG at this age and stop")
    ap.add_argument("--out", default="out", help="output folder")
    ap.add_argument("--jobs", type=int, default=0, help="frames rendered at once (default: CPU cores - 1)")
    a = ap.parse_args()

    model = Model(a.model, a.data_dir)
    pins = []
    for p in a.pin:
        label, la, lo = parse_place(p)
        plate, ground_age = model.plate_of(la, lo)
        print(f"{label}: plate {plate}, ground there since {ground_age:,.0f} Ma")
        pins.append((label, la, lo, plate, ground_age))
    follow = None
    if a.follow:
        follow = next((p for p in pins if p[0].lower() == a.follow.lower()), None)
        if follow is None:
            raise SystemExit(f"--follow {a.follow!r} must match one of the --pin labels")

    fonts = {"big": font(96 * SS), "small": font(32 * SS), "tiny": font(18 * SS), "pin": font(22 * SS)}
    globe = Globe(W * SS * 0.58, H * SS * 0.5, H * SS * 0.42)
    os.makedirs(a.out, exist_ok=True)

    def aim(t, prev):
        if follow and t <= follow[4]:
            lat, lon = model.point_at(follow[1], follow[2], t, follow[3])
            return ease_view(prev, (lon, max(-35.0, min(35.0, lat))))
        return prev or (a.lon, a.lat)

    if a.still is not None:
        t = min(max(a.still, 0), model.oldest)
        path = os.path.join(a.out, f"{a.model}_{t:.0f}Ma.png")
        frame(model, t, aim(t, None), pins, not a.no_boundaries, globe, fonts).save(path)
        print("->", path)
        return

    start, end = min(max(a.start, 0), model.oldest), min(max(a.end, 0), model.oldest)
    n = max(2, int(round(abs(end - start) / a.rate * a.fps)) + 1)
    ages = np.linspace(start, end, n)
    fdir = os.path.join(a.out, "frames")
    os.makedirs(fdir, exist_ok=True)                  # frames are overwritten; ffmpeg reads only the first n
    jobs, view = [], None
    for i, t in enumerate(ages):                       # work out the camera for every frame first
        view = aim(t, view)
        jobs.append((i, float(t), view))
    workers = max(1, a.jobs or (os.cpu_count() or 2) - 1)
    print(f"{n} frames on {workers} workers")
    args = (a.model, a.data_dir, pins, not a.no_boundaries, fdir)
    if workers == 1:
        _init(*args)
        for k, job in enumerate(jobs):
            _render(job)
            if k % 30 == 0 or k == n - 1:
                print(f"frame {k + 1}/{n}", flush=True)
    else:
        with mp.Pool(workers, _init, args) as pool:   # each worker loads the model once
            for k, _ in enumerate(pool.imap(_render, jobs, chunksize=10)):
                if k % 30 == 0 or k == n - 1:
                    print(f"frame {k + 1}/{n}", flush=True)

    video = os.path.join(a.out, f"rewind_{a.model}_{start:.0f}-{end:.0f}Ma.mp4")
    if shutil.which("ffmpeg"):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(a.fps),
                        "-i", os.path.join(fdir, "%05d.png"), "-frames:v", str(n), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-crf", "18", video], check=True)
        print("->", video)
    else:
        print(f"No ffmpeg found. Frames are in {fdir}; join them with any video tool.")


if __name__ == "__main__":
    main()
