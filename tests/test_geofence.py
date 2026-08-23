from app.geofence import DEFAULT_GEOFENCE, contains
from app.schemas import Location


def test_default_zone_contains_its_center():
    assert contains(Location(latitude=17.6860, longitude=83.2180), DEFAULT_GEOFENCE)


def test_default_zone_excludes_distant_point():
    assert not contains(Location(latitude=17.6900, longitude=83.2180), DEFAULT_GEOFENCE)
