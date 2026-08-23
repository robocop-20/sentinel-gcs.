import pytest

from app.config import Settings


def test_class_specific_detection_policy_is_monotonic():
    settings = Settings()
    settings.validate()
    for object_class in ("person", "vessel", "vehicle", "container"):
        assert settings.candidate_confidence_for(
            object_class
        ) <= settings.publish_confidence_for(object_class)
        assert settings.confirmation_frames_for(object_class) >= 1
        assert 0 <= settings.track_mean_confidence_for(object_class) <= 1


def test_invalid_track_lifecycle_order_is_rejected():
    settings = Settings(
        active_track_ttl_s=5,
        track_occluded_after_s=4,
        track_temporarily_lost_after_s=3,
    )
    with pytest.raises(ValueError, match="track lifecycle thresholds"):
        settings.validate()


def test_ray_plane_mode_requires_intrinsics():
    settings = Settings(
        enable_ray_plane_geolocation=True,
        camera_fx_px=0,
        camera_fy_px=0,
    )
    with pytest.raises(ValueError, match="requires positive"):
        settings.validate()


def test_v2x_requires_an_explicit_peer_allowlist():
    settings = Settings(
        enable_v2x=True,
        v2x_shared_secret="test-only-secret",
        v2x_allowed_sources="",
    )
    with pytest.raises(ValueError, match="V2X_ALLOWED_SOURCES"):
        settings.validate()
