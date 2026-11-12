# Rewind Earth

Rewind the plates on a globe, from today back as far as 1.8 billion years, and find out where any place on Earth used to be.

This is the plain, open version of the data behind the ExaCortex video **[Where Was Your Hometown 200 Million Years Ago?](https://www.youtube.com/watch?v=PoDrDVkxvcw)**. It uses the same plate models and the same math, so you get the same numbers, just drawn simply.

| | |
|---|---|
| `rewind.py` | Renders a rewinding globe to video (coastlines, plate boundaries, city pins, age counter) |
| `hometown.py` | Prints and saves where a place was at each age, in one or both models |
| `plates.py` | Loads a plate model and moves points through time (plain pygplates) |

## Install

Python 3.9+ and [ffmpeg](https://ffmpeg.org/download.html) (only needed to join frames into a video).

```
pip install -r requirements.txt
```

The first run downloads the plate model (about 65 MB each) into `./data/`. After that it works offline.

## Where was my hometown?

```
python hometown.py London
python hometown.py "29.95,-90.07,New Orleans" --every 50 --end 600
python hometown.py Beijing --every 100 --end 600
```

```
    Ma             Muller2025                Cao2024
     0      39.9°,     116.4°      39.9°,     116.4°
   100      47.4°,     109.7°      44.3°,     128.3°
   ...
   600     -21.2°,     143.6°      37.9°,      99.8°
```

That last line is the shot from the video where the two models disagree: one puts Beijing south of the equator 600 million years ago, the other puts it in the northern mid-latitudes. A CSV goes to `./out/`.

## Rewind the globe

```
python rewind.py                                          # 0 to 200 Ma, 10 million years per second
python rewind.py --end 600 --pin London --pin Beijing --follow London
python rewind.py --still 250 --pin "40.7,-74.0,Home"      # one PNG, quick check
python rewind.py --model Cao2024 --end 1800 --rate 60     # all the way back
```

| Option | What it does |
|---|---|
| `--model` | `Muller2025` (default) or `Cao2024` |
| `--start`, `--end` | Ages in millions of years ago (Ma). Put `--start` older than `--end` to play forward |
| `--rate` | Millions of years per second of video |
| `--pin` | A city from the list in `plates.py`, `"lat,lon"` or `"lat,lon,Label"`. Repeat for more |
| `--follow` | Turn the globe to keep one pin facing you |
| `--lon`, `--lat` | Fixed view when not following |
| `--no-boundaries` | Skip plate boundaries (faster) |
| `--jobs` | Frames rendered at once (default: CPU cores minus one) |

Each frame takes 1 to 2 seconds on one core, so more cores help a lot. Frames go to `out/frames/`, the video to `out/`.

## How it works

1. **Coastlines.** Every frame calls `pygplates.reconstruct` on the model's coastline polygons at that age. Fractional ages are fine, so the motion is smooth.
2. **Plate boundaries.** `pygplates.resolve_topologies` at the nearest whole million years.
3. **Pins.** Each place is matched to a plate using the model's static polygons today, then rotated back with that plate's rotation. A pin disappears at ages older than the ground under it.
4. **Drawing.** Land is filled on a flat latitude/longitude map, then wrapped onto an orthographic globe with NumPy and Pillow.

Nothing is placed by hand. If a coastline or a pin is somewhere, the model put it there.

## Things to know

- **Latitude is the safer number.** Before about 1 billion years ago, longitudes are poorly pinned down in every model.
- **The models disagree, sometimes by a lot.** That's real uncertainty in the science, not a bug. Run both and compare.
- **Places near plate edges** can land on the wrong plate. `hometown.py` prints the plate ID so you can check.
- **The model stops at 1.8 billion years.** Anything older is outside these reconstructions.

## Data and credit

- **Müller et al. (2025)**, 1.8 billion years of plate motion in a mantle reference frame. Data on Zenodo, CC BY 4.0: https://zenodo.org/records/17353904
- **Cao et al. (2024)**. Data on Zenodo, CC BY 4.0: https://zenodo.org/records/13628813
- Models downloaded with [plate-model-manager](https://github.com/GPlates/plate-model-manager) and reconstructed with [pygplates](https://www.gplates.org/docs/pygplates/), both from the GPlates / EarthByte team.

If you use the models in your own work, cite the papers above.

## License

GPL-2.0-or-later, to match pygplates and plate-model-manager. See `LICENSE`.

The finished ExaCortex videos (their look, animation, narration and music) are not part of this repo.
