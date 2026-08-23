import hashlib
import json

from .schemas import Geofence, Location


def geofence_version(geofence: Geofence) -> str:
    """Content-address a deterministic geofence definition."""
    canonical = json.dumps(
        {
            "id": geofence.id,
            "name": geofence.name,
            "restricted": geofence.restricted,
            "coordinates": geofence.coordinates,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


DEFAULT_GEOFENCE = Geofence(
    id="restricted-zone-a",
    name="Restricted Zone A",
    restricted=True,
    coordinates=[
        (17.6855, 83.2173),
        (17.6855, 83.2190),
        (17.6866, 83.2190),
        (17.6866, 83.2173),
    ],
)
DEFAULT_GEOFENCE = DEFAULT_GEOFENCE.model_copy(
    update={"version": geofence_version(DEFAULT_GEOFENCE)}
)


def contains(location: Location, geofence: Geofence) -> bool:
    """Ray-casting check; points use (latitude, longitude)."""
    y, x = location.latitude, location.longitude
    points = geofence.coordinates
    inside = False
    for index, (lat_a, lon_a) in enumerate(points):
        lat_b, lon_b = points[(index + 1) % len(points)]
        if (lat_a > y) != (lat_b > y):
            crossing = (lon_b - lon_a) * (y - lat_a) / (lat_b - lat_a) + lon_a
            if x < crossing:
                inside = not inside
    return inside
