"""Root fixtures. Every test gets its own data home: persisting commands never write into ./data."""
must never write into the repository's ./data, and a stray database there must never change another test."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path_factory, monkeypatch):
    monkeypatch.setenv("ROBOTEVALOPS_HOME", str(tmp_path_factory.mktemp("roe_home")))
