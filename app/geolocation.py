"""Deliberately conservative flat-ground location estimate.

This is not a calibrated ray/terrain solution.  It is intended only to make
the UI and event path usable until camera calibration is performed.
"""

from math import cos, pi, radians, sin, tan
from .schemas import Location, RangeMeasurement, Telemetry


METRES_PER_DEGREE_LATITUDE = 111_320.0


def _undistort_normalized(
    distorted_x: float,
    distorted_y: float,
    coefficients: tuple[float, ...] | None,
) -> tuple[float, float]:
    """Invert OpenCV radial/tangential distortion with bounded iteration."""
    if not coefficients or len(coefficients) < 4:
        return distorted_x, distorted_y
    k1, k2, p1, p2 = coefficients[:4]
    k3 = coefficients[4] if len(coefficients) > 4 else 0.0
    x, y = distorted_x, distorted_y
    for _ in range(8):
        radius_squared = x * x + y * y
        radial = (
            1
            + k1 * radius_squared
            + k2 * radius_squared**2
            + k3 * radius_squared**3
        )
        if abs(radial) < 1e-9:
            break
        tangent_x = 2 * p1 * x * y + p2 * (radius_squared + 2 * x * x)
        tangent_y = p1 * (radius_squared + 2 * y * y) + 2 * p2 * x * y
        x = (distorted_x - tangent_x) / radial
        y = (distorted_y - tangent_y) / radial
    return x, y


def _mat_vec(
    matrix: tuple[float, ...], vector: tuple[float, float, float]
) -> tuple[float, float, float]:
    return tuple(
        sum(matrix[row * 3 + col] * vector[col] for col in range(3)) for row in range(3)
    )


def _body_to_ned(
    vector: tuple[float, float, float],
    heading_deg: float,
    pitch_deg: float,
    roll_deg: float,
) -> tuple[float, float, float]:
    """Rotate a forward-right-down vector to North-East-Down using aircraft Euler pose."""
    yaw, pitch, roll = map(radians, (heading_deg, pitch_deg, roll_deg))
    cy, sy, cp, sp, cr, sr = (
        cos(yaw),
        sin(yaw),
        cos(pitch),
        sin(pitch),
        cos(roll),
        sin(roll),
    )
    matrix = (
        cy * cp,
        cy * sp * sr - sy * cr,
        cy * sp * cr + sy * sr,
        sy * cp,
        sy * sp * sr + cy * cr,
        sy * sp * cr - cy * sr,
        -sp,
        cp * sr,
        cp * cr,
    )
    return _mat_vec(matrix, vector)


def estimate_location(
    pixel_x: float,
    pixel_y: float,
    frame_width: int,
    frame_height: int,
    telemetry: Telemetry,
    horizontal_fov_deg: float,
    vertical_fov_deg: float,
    range_measurement: RangeMeasurement | None = None,
    camera_fx_px: float = 0,
    camera_fy_px: float = 0,
    camera_cx_px: float = 0,
    camera_cy_px: float = 0,
    ray_plane_enabled: bool = False,
    camera_to_body_matrix: tuple[float, ...] | None = None,
    observation_timestamp: float | None = None,
    distortion_coefficients: tuple[float, ...] | None = None,
) -> Location:
    """Intersect a downward camera ray with a flat ground plane.

    LiDAR, when fresh and downward-facing, supplies the camera-to-ground height.
    Camera intrinsics improve the ray estimate but this remains *approximate* until
    camera extrinsics and ground elevation have been calibrated in the field.
    """
    altitude = telemetry.altitude_m
    if range_measurement and range_measurement.orientation == "downward":
        altitude = range_measurement.distance_m
    altitude = max(altitude, 0.1)
    synchronization_delta_s = (
        abs(observation_timestamp - telemetry.timestamp)
        if observation_timestamp is not None
        else None
    )
    location_metadata = {
        "uncertainty_m": None,
        "uncertainty_status": "UNBOUNDED",
        "synchronization_delta_s": synchronization_delta_s,
        "telemetry_timestamp": telemetry.timestamp,
        "range_timestamp": range_measurement.timestamp if range_measurement else None,
    }
    uses_intrinsics = camera_fx_px > 0 and camera_fy_px > 0
    normalized_x = normalized_y = 0.0
    if uses_intrinsics:
        cx = camera_cx_px or frame_width / 2
        cy = camera_cy_px or frame_height / 2
        normalized_x, normalized_y = _undistort_normalized(
            (pixel_x - cx) / camera_fx_px,
            (pixel_y - cy) / camera_fy_px,
            distortion_coefficients,
        )
    if (
        ray_plane_enabled
        and uses_intrinsics
        and camera_to_body_matrix
        and telemetry.attitude_valid
    ):
        ray_camera = (normalized_x, normalized_y, 1.0)
        ray_body = _mat_vec(camera_to_body_matrix, ray_camera)
        north_ray, east_ray, down_ray = _body_to_ned(
            ray_body, telemetry.heading_deg, telemetry.pitch_deg, telemetry.roll_deg
        )
        if down_ray > 1e-6:
            north, east = (
                altitude * north_ray / down_ray,
                altitude * east_ray / down_ray,
            )
            latitude = telemetry.latitude + north / METRES_PER_DEGREE_LATITUDE
            longitude_scale = METRES_PER_DEGREE_LATITUDE * max(
                cos(telemetry.latitude * pi / 180), 1e-8
            )
            return Location(
                latitude=latitude,
                longitude=telemetry.longitude + east / longitude_scale,
                approximate=True,
                method="ray_plane",
                **location_metadata,
            )
    if uses_intrinsics:
        east_camera = normalized_x * altitude
        north_camera = -normalized_y * altitude
    else:
        x_normalized = (pixel_x - frame_width / 2) / (frame_width / 2)
        y_normalized = (pixel_y - frame_height / 2) / (frame_height / 2)
        east_camera = x_normalized * altitude * tan(radians(horizontal_fov_deg / 2))
        north_camera = -y_normalized * altitude * tan(radians(vertical_fov_deg / 2))
    # First-order compensation for vehicle attitude; a calibrated transform will
    # replace this correction when camera extrinsics and terrain are available.
    if telemetry.attitude_valid:
        east_camera += altitude * tan(radians(telemetry.roll_deg))
        north_camera += altitude * tan(radians(telemetry.pitch_deg))
    heading = radians(telemetry.heading_deg)
    east = east_camera * cos(heading) + north_camera * sin(heading)
    north = -east_camera * sin(heading) + north_camera * cos(heading)
    latitude = telemetry.latitude + north / METRES_PER_DEGREE_LATITUDE
    longitude_scale = METRES_PER_DEGREE_LATITUDE * max(
        cos(telemetry.latitude * pi / 180), 1e-8
    )
    longitude = telemetry.longitude + east / longitude_scale
    return Location(
        latitude=latitude,
        longitude=longitude,
        approximate=True,
        method="flat_ground_intrinsics" if uses_intrinsics else "flat_ground_fov",
        **location_metadata,
    )
