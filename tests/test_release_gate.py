import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"


def test_release_gate_requires_quality_latency_and_calibration(tmp_path):
    output = tmp_path / "gate.json"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "training" / "release_gate.py"),
            "--report",
            str(FIXTURES / "port-evaluation.synthetic.json"),
            "--latency-report",
            str(FIXTURES / "inference-benchmark.synthetic.json"),
            "--calibration-report",
            str(FIXTURES / "confidence-calibration-report.synthetic.json"),
            "--output",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(output.read_text(encoding="utf-8"))["passed"] is True
