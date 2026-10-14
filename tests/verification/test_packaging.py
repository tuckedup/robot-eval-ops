"""Audit A5: the built wheel must carry its default configs and work outside the checkout."""

from __future__ import annotations

import shutil
import subprocess
import zipfile

import pytest

from robotevalops.controllers.base import configs_dir

EXPECTED = (
    "eval_smoke_mock.yaml",
    "eval_smoke_sim.yaml",
    "eval_full_sim.yaml",
    "controllers/mock_scripted.yaml",
    "controllers/sim_scripted.yaml",
    "conditions/mock_conditions.yaml",
    "conditions/sim_conditions.yaml",
    "hardware/so101.example.yaml",
)


def test_default_configs_live_inside_the_package():
    for rel in EXPECTED:
        assert (configs_dir() / rel).is_file(), rel


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv not available to build a wheel")
def test_built_wheel_contains_default_configs(tmp_path):
    p = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert p.returncode == 0, p.stderr[-800:]
    (whl,) = tmp_path.glob("robotevalops-*.whl")
    names = set(zipfile.ZipFile(whl).namelist())
    missing = [e for e in EXPECTED if f"robotevalops/configs/{e}" not in names]
    assert not missing, f"wheel lacks default configs: {missing}"
