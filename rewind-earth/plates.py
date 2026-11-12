"""plates.py - load an open plate model and move points on it back through time.

Everything here is plain pygplates. The models are downloaded once with plate-model-manager
into ./data/<model>/ and read from there after that.
"""
import glob
import os

import pygplates

MODELS = {
    "Muller2025": "Muller et al. 2025 (EarthByte), CC BY 4.0",
    "Cao2024": "Cao et al. 2024 (EarthByte), CC BY 4.0",
}

# A few cities to start with. Any lat/lon works too.
CITIES = {
    "New York": (40.71, -74.01), "London": (51.51, -0.13), "Paris": (48.86, 2.35),
    "Chicago": (41.88, -87.63), "Mexico City": (19.43, -99.13), "Sao Paulo": (-23.55, -46.63),
    "Cape Town": (-33.92, 18.42), "Cairo": (30.04, 31.24), "Mumbai": (19.08, 72.88),
    "Tokyo": (35.68, 139.69), "Sydney": (-33.87, 151.21), "Beijing": (39.90, 116.40),
    "Moscow": (55.76, 37.62), "Los Angeles": (34.05, -118.24), "Miami": (25.76, -80.19),
    "Reykjavik": (64.15, -21.94),
}


def _download(name, data_dir):
    from plate_model_manager import PlateModelManager
    print(f"Downloading {name} into {data_dir} (one time only) ...")
    model = PlateModelManager().get_model(name, data_dir=data_dir)
    model.get_rotation_model()
    model.get_coastlines()
    model.get_static_polygons()
    model.get_topologies()


class Model:
    """One plate model: rotations, coastlines, static polygons and plate boundaries."""

    def __init__(self, name="Muller2025", data_dir="data"):
        if name not in MODELS:
            raise SystemExit(f"Unknown model {name!r}. Pick one of: {', '.join(MODELS)}")
        self.name = name
        self.credit = MODELS[name]
        folder = os.path.join(data_dir, name.lower())
        if not glob.glob(os.path.join(folder, "Rotations", "*.rot")):
            _download(name, data_dir)

        def files(sub, pattern):
            found = sorted(glob.glob(os.path.join(folder, sub, pattern)))
            if not found:
                raise SystemExit(f"No {sub} files in {folder}. Delete the folder and run again to re-download.")
            return found

        self.rotation = pygplates.RotationModel(files("Rotations", "*.rot"))
        self.coastlines = pygplates.FeatureCollection(files("Coastlines", "*.gpml*")[0])
        self.static = pygplates.FeatureCollection(files("StaticPolygons", "*.gpml*")[0])
        self.topologies = [pygplates.FeatureCollection(f) for f in files("Topologies", "*.gpml*")]
        self._partitioner = pygplates.PlatePartitioner(self.static, self.rotation, 0)
        self._topo_cache = {}
        self.oldest = 1800.0

    # ---- land -------------------------------------------------------------------------
    def coastlines_at(self, t):
        """List of (N, 2) [lat, lon] arrays: the coastline polygons at t million years ago."""
        out = []
        pygplates.reconstruct(self.coastlines, self.rotation, out, float(t))
        return [r.get_reconstructed_geometry().to_lat_lon_array() for r in out]

    # ---- plate boundaries ---------------------------------------------------------------
    def boundaries_at(self, t):
        """List of (N, 2) [lat, lon] polylines: resolved plate boundaries at whole-Myr t."""
        t = int(round(t))
        if t not in self._topo_cache:
            if len(self._topo_cache) > 8:
                self._topo_cache.clear()
            topos, sections = [], []
            pygplates.resolve_topologies(self.topologies, self.rotation, topos, float(t), sections)
            lines = []
            for sec in sections:
                for sub in sec.get_shared_sub_segments():
                    a = sub.get_resolved_geometry().to_lat_lon_array()
                    if len(a) > 1:
                        lines.append(a)
            self._topo_cache[t] = lines
        return self._topo_cache[t]

    # ---- points (cities) ----------------------------------------------------------------
    def plate_of(self, lat, lon):
        """(plate id, age of the ground in Ma) under a present-day point, from the static polygons."""
        hit = self._partitioner.partition_point(pygplates.PointOnSphere(lat, lon))
        if hit is None:
            return 0, 0.0
        f = hit.get_feature()
        return f.get_reconstruction_plate_id(), float(min(f.get_valid_time()[0], 1e9))

    def point_at(self, lat, lon, t, plate=None):
        """Where a present-day point was at t Ma: (lat, lon). Same math as pygplates.reconstruct."""
        if plate is None:
            plate, _ = self.plate_of(lat, lon)
        p = self.rotation.get_rotation(float(t), plate) * pygplates.PointOnSphere(lat, lon)
        return p.to_lat_lon()


def parse_place(text):
    """'London' or '51.5,-0.1' or '51.5,-0.1,My town' -> (label, lat, lon)."""
    for name, (la, lo) in CITIES.items():
        if name.lower() == text.strip().lower():
            return name, la, lo
    parts = [p.strip() for p in text.split(",")]
    try:
        la, lo = float(parts[0]), float(parts[1])
    except (ValueError, IndexError):
        raise SystemExit(f"Can't read place {text!r}. Use a city from the list ({', '.join(CITIES)}) "
                         f"or 'lat,lon' or 'lat,lon,Label'.")
    return (parts[2] if len(parts) > 2 else f"{la:.2f},{lo:.2f}"), la, lo
