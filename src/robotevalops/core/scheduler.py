"""Deterministic, paired trial schedule.

Order: for each condition (config order) -> each trial_index (0..n-1) -> each controller (config order).
The seed depends only on (base_seed, condition_name, trial_index), so every controller sees the same seed
for a given cell (paired design). The same EvalConfig always yields an identical schedule.
"""

from __future__ import annotations

from dataclasses import dataclass

from robotevalops.schemas import ConditionSpec, ControllerSpec, EvalConfig
from robotevalops.util import derive_seed


@dataclass(frozen=True)
class PlannedTrial:
    schedule_position: int
    controller: ControllerSpec
    condition: ConditionSpec
    trial_index: int
    seed: int


def build_schedule(config: EvalConfig) -> list[PlannedTrial]:
    out: list[PlannedTrial] = []
    pos = 0
    for condition in config.conditions:
        for trial_index in range(config.trials_per_condition):
            seed = derive_seed(config.base_seed, condition.name, trial_index)
            for controller in config.controllers:
                out.append(PlannedTrial(pos, controller, condition, trial_index, seed))
                pos += 1
    return out
