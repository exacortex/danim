"""hometown.py - where was a place at each age? Prints a table and writes a CSV.

    python hometown.py London
    python hometown.py "29.95,-90.07,New Orleans" --every 50 --end 600
    python hometown.py Beijing --models Muller2025 Cao2024     # see where the models disagree

Latitudes are the safer number. Before about 1 billion years ago, longitudes are poorly pinned down
in every model, and the two models can disagree by thousands of kilometres.
"""
import argparse
import csv
import os

from plates import MODELS, Model, parse_place


def main():
    ap = argparse.ArgumentParser(description="Ride a place back through time on an open plate model.")
    ap.add_argument("place", help='city name, "lat,lon" or "lat,lon,Label"')
    ap.add_argument("--models", nargs="+", default=list(MODELS), help="one or more of: " + ", ".join(MODELS))
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--every", type=float, default=25, help="step in millions of years")
    ap.add_argument("--end", type=float, default=1800, help="oldest age in Ma")
    ap.add_argument("--out", default="out")
    a = ap.parse_args()

    label, lat, lon = parse_place(a.place)
    ages, t = [], 0.0
    while t <= min(a.end, 1800) + 1e-9:
        ages.append(round(t, 3))
        t += a.every

    table = {}
    for name in a.models:
        m = Model(name, a.data_dir)
        plate, ground_age = m.plate_of(lat, lon)
        print(f"{name}: {label} sits on plate {plate}; that ground is in the model back to {ground_age:,.0f} Ma")
        for t in ages:
            table[(name, t)] = m.point_at(lat, lon, t, plate) if t <= ground_age else None

    head = f"{'Ma':>6} " + " ".join(f"{n:>22}" for n in a.models)
    print("\n" + head)
    for t in ages:
        cells = []
        for n in a.models:
            p = table[(n, t)]
            cells.append(f"{'(no ground yet)':>22}" if p is None else f"{p[0]:>9.1f}°, {p[1]:>9.1f}°")
        print(f"{t:>6.0f} " + " ".join(cells))

    os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.out, f"hometown_{label.replace(' ', '_').replace(',', '_')}.csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["place", "model", "age_Ma", "paleo_lat", "paleo_lon"])
        for t in ages:
            for n in a.models:
                p = table[(n, t)]
                w.writerow([label, n, t, *(("", "") if p is None else (round(p[0], 2), round(p[1], 2)))])
    print("\n->", path)


if __name__ == "__main__":
    main()
