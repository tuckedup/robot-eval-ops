"""Fault registry: run F01-F09 here and F10 lazily from core (Core owns the scenario)."""

from __future__ import annotations

import importlib
import tempfile
import traceback
from pathlib import Path

from robotevalops.faults.cases import CASE_IDS, CASES
from robotevalops.schemas import FaultResult, QACode
from robotevalops.util import utcnow

_EXPECTED = {
    "F01_missing_video": QACode.MISSING_VIDEO,
    "F02_truncated_video": QACode.TRUNCATED_VIDEO,
    "F03_nonmonotonic_timestamps": QACode.NONMONOTONIC_TIMESTAMPS,
    "F04_nonfinite_action": QACode.NONFINITE_VALUE,
    "F05_wrong_schema": QACode.SCHEMA_MISMATCH,
    "F06_missing_model_artifact": QACode.MISSING_MODEL_ARTIFACT,
    "F07_duplicate_trial_id": QACode.DUPLICATE_ID,
    "F08_hash_mismatch": QACode.HASH_MISMATCH,
    "F09_transfer_timeout": QACode.TRANSFER_TIMEOUT,
    "F10_interrupted_runner": QACode.INTERRUPTED_RUNNER,
}


def _not_executed(case_id: str, reason: str) -> FaultResult:
    """A case that did not run (or crashed) is reported as such: detected=False, never passed."""
    return FaultResult(
        case_id=case_id,
        description="NOT EXECUTED",
        expected_code=_EXPECTED[case_id],
        detected=False,
        message=reason,
        executed_at=utcnow(),
        details={"executed": False, "reason": reason},
    )


def run_f10(workdir: Path) -> FaultResult:
    try:
        mod = importlib.import_module("robotevalops.core.fault_interrupted")
        fn = mod.run_interrupted_runner_case
    except (ImportError, AttributeError) as exc:
        return _not_executed(
            "F10_interrupted_runner", f"core.fault_interrupted.run_interrupted_runner_case unavailable: {exc}"
        )
    try:
        res: FaultResult = fn(workdir / "F10")
    except Exception as exc:
        return _not_executed(
            "F10_interrupted_runner",
            f"scenario crashed: {type(exc).__name__}: {exc}\n{traceback.format_exc(limit=3)}",
        )
    res.details.setdefault("executed", True)
    return res


def run_all(workdir: str | Path | None = None) -> list[FaultResult]:
    """Run every case (each in its own subdirectory) and return results in id order F01..F10."""
    base = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="roe-faults-"))
    base.mkdir(parents=True, exist_ok=True)
    results: list[FaultResult] = []
    for cid in CASE_IDS:
        if cid == "F10_interrupted_runner":
            results.append(run_f10(base))
            continue
        d = base / cid
        d.mkdir(parents=True, exist_ok=True)
        try:
            res = CASES[cid](d)
            res.details.setdefault("executed", True)
            results.append(res)
        except Exception as exc:  # a crashing case is a failure to report, not to hide
            results.append(_not_executed(cid, f"case crashed: {type(exc).__name__}: {exc}"))
    return results
