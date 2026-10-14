"""Load and validate EvalConfig YAML templates (src/robotevalops/configs/eval_*.yaml).

Controllers and conditions may be given inline (`controllers:` / `conditions:`) or as paths to YAML list files
(`controllers_from:` / `conditions_from:`). Relative paths are resolved against the config file's directory
first, then against the repo root (nearest parent of the config containing pyproject.toml).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from robotevalops.errors import RobotEvalOpsError
from robotevalops.schemas import ConditionSpec, ControllerSpec, EvalConfig, Provenance


class ConfigError(RobotEvalOpsError):
    """An eval config file is missing, malformed or inconsistent. The message says what to fix."""


def find_repo_root(start: Path) -> Path | None:
    for p in (start, *start.parents):
        if (p / "pyproject.toml").is_file():
            return p
    return None


def _read_yaml(path: Path) -> Any:
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f)
    except FileNotFoundError as e:
        raise ConfigError(f"config file not found: {path}") from e
    except yaml.YAMLError as e:
        raise ConfigError(f"invalid YAML in {path}: {e}") from e


def _resolve_ref(ref: str, cfg_path: Path, key: str) -> Path:
    p = Path(ref)
    if p.is_absolute():
        candidates = [p]
    else:
        # config-file directory FIRST (an installed wheel has no repo root, and an unrelated pyproject.toml in
        # an ancestor directory must never shadow the config's own sibling files), then the repo root.
        candidates = [cfg_path.parent / p]
        root = find_repo_root(cfg_path.parent.resolve())
        if root is not None:
            candidates.append(root / p)
    for c in candidates:
        if c.is_file():
            return c
    tried = ", ".join(str(c) for c in candidates)
    raise ConfigError(f"{cfg_path.name}: {key} {ref!r} not found (tried: {tried})")


def _load_list(ref: str, cfg_path: Path, key: str, list_key: str) -> list[Any]:
    path = _resolve_ref(ref, cfg_path, key)
    data = _read_yaml(path)
    if isinstance(data, dict) and isinstance(data.get(list_key), list):
        data = data[list_key]
    if not isinstance(data, list) or not data:
        raise ConfigError(
            f"{path}: expected a non-empty YAML list of {list_key} (or a mapping with '{list_key}:')"
        )
    return data


def _items(raw: dict[str, Any], cfg_path: Path, inline: str, from_key: str) -> list[Any]:
    has_inline, has_from = inline in raw, from_key in raw
    if has_inline and has_from:
        raise ConfigError(f"{cfg_path.name}: give either '{inline}' or '{from_key}', not both")
    if not has_inline and not has_from:
        raise ConfigError(f"{cfg_path.name}: missing '{inline}' (or '{from_key}: <path to a YAML list>')")
    if has_from:
        ref = raw[from_key]
        if not isinstance(ref, str) or not ref.strip():
            raise ConfigError(f"{cfg_path.name}: '{from_key}' must be a path string")
        return _load_list(ref, cfg_path, from_key, inline)
    value = raw[inline]
    if not isinstance(value, list) or not value:
        raise ConfigError(f"{cfg_path.name}: '{inline}' must be a non-empty list")
    return value


def _validate_items(model: Any, items: list[Any], label: str, cfg_path: Path) -> list[Any]:
    out = []
    for i, item in enumerate(items):
        try:
            out.append(model.model_validate(item))
        except ValidationError as e:
            raise ConfigError(f"{cfg_path.name}: invalid {label}[{i}]: {_short(e)}") from e
    return out


def _short(e: ValidationError) -> str:
    return "; ".join(f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors())


def load_eval_config(path: str | Path) -> EvalConfig:
    cfg_path = Path(path).resolve()
    raw = _read_yaml(cfg_path)
    if not isinstance(raw, dict):
        raise ConfigError(f"{cfg_path.name}: top level must be a mapping")
    raw = dict(raw)
    controllers = _validate_items(
        ControllerSpec, _items(raw, cfg_path, "controllers", "controllers_from"), "controllers", cfg_path
    )
    conditions = _validate_items(
        ConditionSpec, _items(raw, cfg_path, "conditions", "conditions_from"), "conditions", cfg_path
    )
    for k in ("controllers", "controllers_from", "conditions", "conditions_from"):
        raw.pop(k, None)
    try:
        cfg = EvalConfig.model_validate({**raw, "controllers": controllers, "conditions": conditions})
    except ValidationError as e:
        raise ConfigError(f"{cfg_path.name}: {_short(e)}") from e
    _check(cfg, cfg_path)
    return cfg


def _check(cfg: EvalConfig, cfg_path: Path) -> None:
    dup_c = _dups(c.controller_id for c in cfg.controllers)
    if dup_c:
        raise ConfigError(f"{cfg_path.name}: duplicate controller_id(s): {dup_c}")
    dup_k = _dups(c.name for c in cfg.conditions)
    if dup_k:
        raise ConfigError(f"{cfg_path.name}: duplicate condition name(s): {dup_k}")
    if (cfg.provenance == Provenance.MOCK) != (cfg.backend == "mock"):
        raise ConfigError(
            f"{cfg_path.name}: provenance '{cfg.provenance.value}' and backend '{cfg.backend}' are inconsistent "  # noqa: E501
            "(provenance mock <=> backend mock)"
        )


def _dups(values: Any) -> list[str]:
    seen: set[str] = set()
    dup: list[str] = []
    for v in values:
        if v in seen and v not in dup:
            dup.append(v)
        seen.add(v)
    return dup
