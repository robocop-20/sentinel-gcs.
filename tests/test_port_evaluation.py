from training.evaluate_port_model import _iou


def test_calibration_match_iou_geometry():
    assert _iou([0, 0, 10, 10], [0, 0, 10, 10]) == 1.0
    assert _iou([0, 0, 1, 1], [2, 2, 3, 3]) == 0.0
    assert _iou([0, 0, 2, 2], [1, 1, 3, 3]) == 1 / 7
