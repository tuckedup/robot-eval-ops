"""Shared controller/condition helpers: YAML loading, seeded RNG, deterministic hash units."""

from __future__ import annotations

import hashlib
from importlib import resources
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from robotevalops.errors import RobotEvalOpsError
from robotevalops.schemas import ConditionSpec, ControllerSpec


class StopRequestedError(RobotEvalOpsError):
    """A command was issued after a software stop request (act() must raise, never move)."""


def configs_dir() -> Path:
    """Default YAML configs shipped INSIDE the package (`robotevalops/configs`), so an installed wheel works
    from any directory. Users may still pass their own config paths explicitly."""
    return Path(str(resources.files("robotevalops").joinpath("configs")))


def _load_list(path: str | Path) -> list[dict[str, Any]]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise RobotEvalOpsError(f"{path}: expected a YAML list of mappings at the top level")
    return data


def load_conditions(path: str | Path) -> list[ConditionSpec]:
    return [ConditionSpec.model_validate(d) for d in _load_list(path)]


def load_controller_specs(path: str | Path) -> list[ControllerSpec]:
    return [ControllerSpec.model_validate(d) for d in _load_list(path)]


def condition_param(cond: ConditionSpec, key: str, default: float) -> float:
    v = cond.params.get(key, default)
    return float(v)


def stable_digest(*parts: object) -> bytes:
    return hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).digest()


def unit_from_hash(*parts: object) -> float:
    """Deterministic float in [0, 1) from the SHA-256 of the parts (first 8 bytes / 2**64)."""
    return int.from_bytes(stable_digest(*parts)[:8], "big") / 2**64


def seeded_rng(seed: int, *labels: object) -> np.random.Generator:
    """Independent reproducible stream per (seed, labels); visual and state streams never mix."""
    s = int.from_bytes(stable_digest(seed, *labels)[:8], "big")
    return np.random.default_rng(s)
