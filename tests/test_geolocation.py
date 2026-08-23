from app.geolocation import estimate_location
from app.schemas import Telemetry


def telemetry():
    return Telemetry(
        timestamp=1, latitude=17.686, longitude=83.218, altitude_m=40, heading_deg=0
    )


def test_image_center_is_drone_position():
    result = estimate_location(640, 360, 1280, 720, telemetry(), 92, 60)
    assert result.latitude == telemetry().latitude
    assert result.longitude == telemetry().longitude


def test_right_pixel_moves_east_at_north_heading():
    result = estimate_location(1000, 360, 1280, 720, telemetry(), 92, 60)
    assert result.longitude > telemetry().longitude


def test_uncalibrated_location_is_explicitly_unbounded_and_timestamped():
    result = estimate_location(
        640,
        360,
        1280,
        720,
        telemetry(),
        92,
        60,
        observation_timestamp=1.4,
    )
    assert result.approximate is True
    assert result.uncertainty_m is None
    assert result.uncertainty_status == "UNBOUNDED"
    assert result.synchronization_delta_s == 0.4


def test_ray_plane_mode_does_not_use_invalid_attitude():
    result = estimate_location(
        640,
        360,
        1280,
        720,
        telemetry(),
        92,
        60,
        camera_fx_px=500,
        camera_fy_px=500,
        ray_plane_enabled=True,
        camera_to_body_matrix=(1, 0, 0, 0, 1, 0, 0, 0, 1),
    )
    assert result.method == "flat_ground_intrinsics"


def test_intrinsic_mode_applies_configured_distortion_correction():
    uncorrected = estimate_location(
        1000,
        360,
        1280,
        720,
        telemetry(),
        92,
        60,
        camera_fx_px=500,
        camera_fy_px=500,
    )
    corrected = estimate_location(
        1000,
        360,
        1280,
        720,
        telemetry(),
        92,
        60,
        camera_fx_px=500,
        camera_fy_px=500,
        distortion_coefficients=(0.2, 0, 0, 0, 0),
    )
    assert corrected.longitude != uncorrected.longitude
