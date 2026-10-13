from __future__ import annotations

from pathlib import Path

import pytest
from eval_seed import seed_session

from robotevalops.core.service import EvalService


@pytest.fixture
def svc(tmp_path: Path) -> EvalService:
    return EvalService(tmp_path / "home")


@pytest.fixture
def seeded(svc: EvalService):
    return svc, seed_session(svc)
