"""Shared domain contracts (lead-owned). Workers must request changes via the lead.

Key separation (never collapse these into one field):
  provenance      : where the data came from (mock / simulation / imported / hardware)
  controller_type : who produced actions (scripted / learned / teleoperated)
  state           : lifecycle of the attempt (did it run?)
  task_outcome    : did the task succeed (scored separately from lifecycle)
  termination_reason, recording_quality, intervention : independent fields
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from robotevalops.util import RUBRIC_VERSION, SCHEMA_VERSION, config_hash

# --------------------------------------------------------------------------- enums


class Provenance(StrEnum):
    MOCK = "mock"  # seeded fast fixture backend; NEVER evidence of robotics performance
    SIMULATION = "simulation"  # PyBullet Panda physics
    IMPORTED_REAL_RECORDING = "imported_real_recording"  # e.g. a LeRobot dataset someone recorded
    PHYSICAL_HARDWARE = "physical_hardware"  # only when a real device actually ran


class ControllerType(StrEnum):
    SCRIPTED = "scripted"  # parameterised program; a config is NOT a learned checkpoint
    LEARNED = "learned"  # a real trained checkpoint (artifact hash required)
    TELEOPERATED = "teleoperated"


class SessionState(StrEnum):
    PLANNED = "planned"
    PREFLIGHT = "preflight"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"


class TrialState(StrEnum):
    PLANNED = "planned"
    PREFLIGHT = "preflight"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"  # ran to a natural end (success criterion met OR timeout)
    FAILED = "failed"  # infrastructure/recording/preflight failure; task NOT judged
    ABORTED = "aborted"  # stopped by operator/software request or runner interruption


TERMINAL_TRIAL_STATES = frozenset({TrialState.COMPLETED, TrialState.FAILED, TrialState.ABORTED})
TERMINAL_SESSION_STATES = frozenset({SessionState.COMPLETED, SessionState.FAILED, SessionState.ABORTED})


class TaskOutcome(StrEnum):
    UNSCORED = "unscored"
    SUCCESS = "success"
    FAILURE = "failure"


class ScoreSource(StrEnum):
    NONE = "none"
    PHYSICS_EVIDENCE = "physics_evidence"  # derived from recorded simulator state
    OPERATOR_VIDEO = "operator_video"  # human watched the recording
    IMPORTED_LABEL = "imported_label"
    MOCK_FIXTURE = "mock_fixture"


class TerminationReason(StrEnum):
    NOT_RUN = "not_run"
    SUCCESS_CRITERION_MET = "success_criterion_met"
    TIMEOUT = "timeout"
    OPERATOR_ABORT = "operator_abort"
    SOFTWARE_STOP_REQUEST = "software_stop_request"
    INTERRUPTED_RUNNER = "interrupted_runner"  # crash/restart; evidence preserved
    PREFLIGHT_FAILED = "preflight_failed"
    INFRA_FAILURE = "infra_failure"
    RECORDING_FAILURE = "recording_failure"
    SAFETY_STOP = "safety_stop"  # reported by operator; not an e-stop guarantee


INFRA_REASONS = frozenset(
    {
        TerminationReason.INFRA_FAILURE,
        TerminationReason.RECORDING_FAILURE,
        TerminationReason.PREFLIGHT_FAILED,
        TerminationReason.INTERRUPTED_RUNNER,
    }
)


class RecordingQuality(StrEnum):
    UNCHECKED = "unchecked"
    PASS = "pass"
    FLAGGED = "flagged"  # warnings only
    FAIL = "fail"  # error-level QA flags; record quarantined


class Intervention(StrEnum):
    NONE = "none"
    ASSISTED = "assisted"  # any operator assistance => never an autonomous success
    UNKNOWN = "unknown"


class ArtifactRole(StrEnum):
    VIDEO = "video"
    TRACE = "trace"  # state/action jsonl
    LOG = "log"
    MODEL = "model"  # learned checkpoint OR scripted-config file
    MANIFEST = "manifest"
    CONFIG = "config"
    REPORT = "report"
    OTHER = "other"


class ArtifactStatus(StrEnum):
    PENDING = "pending"
    PRESENT = "present"  # exists locally, hash recorded
    MISSING = "missing"
    UPLOADED = "uploaded"
    VERIFIED = "verified"  # downloaded + SHA-256 recomputed and equal
    MISMATCH = "mismatch"
    QUARANTINED = "quarantined"  # moved aside by QA; original evidence preserved
    FAILED = "failed"


class QACode(StrEnum):
    MISSING_VIDEO = "missing_video"
    TRUNCATED_VIDEO = "truncated_video"
    UNDECODABLE_FRAMES = "undecodable_frames"
    NONMONOTONIC_TIMESTAMPS = "nonmonotonic_timestamps"
    NONFINITE_VALUE = "nonfinite_value"
    MISSING_FIELD = "missing_field"
    SCHEMA_MISMATCH = "schema_mismatch"
    MISSING_ARTIFACT = "missing_artifact"
    MISSING_MODEL_ARTIFACT = "missing_model_artifact"
    DUPLICATE_ID = "duplicate_id"
    MISSING_OUTCOME = "missing_outcome"
    HASH_MISMATCH = "hash_mismatch"
    TRANSFER_TIMEOUT = "transfer_timeout"
    INTERRUPTED_RUNNER = "interrupted_runner"
    LOW_COMPLETENESS = "low_completeness"


class Severity(StrEnum):
    WARNING = "warning"
    ERROR = "error"


# --------------------------------------------------------------------------- base


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=False, validate_assignment=True)


# --------------------------------------------------------------------------- specs


class ConditionSpec(_M):
    """A bounded, reproducible evaluation condition."""

    name: str
    kind: str  # nominal | object_position | lighting | background | occlusion | custom
    version: str = "1"
    params: dict[str, float | int | str | bool] = Field(default_factory=dict)
    # True: changes simulator state the state-based controller reads (e.g. block pose).
    # False: visual-only (lighting/background/occlusion) — a scripted state-based controller
    # is expected to be unaffected; this says NOTHING about learned-policy visual robustness.
    affects_controller_state: bool = False
    description: str = ""


class ControllerSpec(_M):
    controller_id: str  # e.g. "scripted_baseline_a"
    type: ControllerType
    version: str
    config: dict[str, Any] = Field(default_factory=dict)
    artifact_relpath: str | None = None  # checkpoint (learned) or exported config file (scripted)
    artifact_sha256: str | None = None
    description: str = ""

    @property
    def config_hash(self) -> str:
        return config_hash({"id": self.controller_id, "type": self.type.value,
                            "version": self.version, "config": self.config})

    @model_validator(mode="after")
    def _learned_needs_artifact(self) -> ControllerSpec:
        if self.type == ControllerType.LEARNED and not self.artifact_sha256:
            raise ValueError("learned controller requires artifact_sha256 (a real checkpoint hash)")
        return self


class TaskSpec(_M):
    task_id: str = "pick_place_block_v1"
    description: str = "Pick the block and place it entirely inside the target region, released."
    rubric_version: str = RUBRIC_VERSION
    attempt_timeout_s: float = 30.0
    dwell_required_s: float = 2.0


class EvalConfig(_M):
    """Full evaluation template: controllers x conditions x trials_per_condition."""

    name: str
    schema_version: str = SCHEMA_VERSION
    task: TaskSpec = Field(default_factory=TaskSpec)
    provenance: Provenance
    backend: str  # "mock" | "pybullet_panda" | "so101_lerobot" | "lerobot_import"
    controllers: list[ControllerSpec]
    conditions: list[ConditionSpec]
    trials_per_condition: int = Field(ge=1)
    base_seed: int = 0

    @property
    def planned_count(self) -> int:
        return len(self.controllers) * len(self.conditions) * self.trials_per_condition

    @property
    def config_hash(self) -> str:
        return config_hash(self.model_dump(mode="json"))


# --------------------------------------------------------------------------- artifacts


class ArtifactRef(_M):
    role: ArtifactRole
    relpath: str  # POSIX, relative to the session run dir (runs/<session_id>/)
    sha256: str | None = None
    size_bytes: int | None = None
    status: ArtifactStatus = ArtifactStatus.PENDING
    detail: str = ""


# --------------------------------------------------------------------------- records


class SessionRecord(_M):
    session_id: str
    name: str
    state: SessionState = SessionState.PLANNED
    provenance: Provenance
    backend: str
    task: TaskSpec = Field(default_factory=TaskSpec)
    purpose: str = "evaluation"  # evaluation | demonstration_collection | preflight_recording
    operator: str = ""
    device_id: str | None = None  # physical device lock key (None for mock/sim)
    calibration_ref: str | None = None  # path/id of a joint-calibration file, hardware only
    eval_config_hash: str | None = None
    software: dict[str, str] = Field(default_factory=dict)
    git_commit: str | None = None
    requires_fresh_preflight: bool = False  # set by crash recovery; cleared by a passing preflight
    operator_ack_at: datetime | None = None  # hardware per-session acknowledgement
    created_at: datetime
    updated_at: datetime
    notes: str = ""
    schema_version: str = SCHEMA_VERSION


class TrialRecord(_M):
    trial_id: str
    session_id: str
    schedule_position: int  # stable order within session
    controller_id: str
    controller_type: ControllerType
    controller_version: str
    controller_config_hash: str
    model_artifact_sha256: str | None = None
    condition_name: str
    condition_kind: str
    trial_index: int
    seed: int
    provenance: Provenance
    backend: str
    state: TrialState = TrialState.PLANNED
    task_outcome: TaskOutcome = TaskOutcome.UNSCORED
    score_source: ScoreSource = ScoreSource.NONE
    rubric_version: str = RUBRIC_VERSION
    termination_reason: TerminationReason = TerminationReason.NOT_RUN
    recording_quality: RecordingQuality = RecordingQuality.UNCHECKED
    intervention: Intervention = Intervention.UNKNOWN
    planned_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_s: float | None = None
    reset_duration_s: float | None = None
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)  # e.g. physics evidence summary
    qa_flags: list[str] = Field(default_factory=list)  # QACode values
    notes: str = ""

    @property
    def is_attempted(self) -> bool:
        """Initiated attempt: reached RUNNING at least once (started_at set)."""
        return self.started_at is not None

    @property
    def is_autonomous_success(self) -> bool:
        return is_autonomous_success(self)


def is_autonomous_success(t: TrialRecord) -> bool:
    """Autonomous success requires ALL of: completed run, scored success, zero intervention,
    and a non-teleoperated controller. Assisted/unknown intervention never counts."""
    return (
        t.state == TrialState.COMPLETED
        and t.task_outcome == TaskOutcome.SUCCESS
        and t.intervention == Intervention.NONE
        and t.controller_type != ControllerType.TELEOPERATED
        and t.recording_quality != RecordingQuality.FAIL
    )


class ScoreEdit(_M):
    edit_id: str
    trial_id: str
    at: datetime
    editor: str
    reason: str  # mandatory, non-empty
    before_outcome: TaskOutcome
    after_outcome: TaskOutcome
    before_intervention: Intervention
    after_intervention: Intervention
    before_source: ScoreSource
    after_source: ScoreSource

    @model_validator(mode="after")
    def _reason(self) -> ScoreEdit:
        if not self.reason.strip():
            raise ValueError("score edits require a non-empty reason")
        return self


# --------------------------------------------------------------------------- recording


class TraceRow(_M):
    """One line of trace.jsonl. t is seconds since trial start (monotonic non-decreasing).
    Quantities are named by the observed thing; simulator frames are rendered, not camera data."""

    i: int
    t: float
    state: list[float]
    action: list[float]


class TraceHeader(_M):
    """First line of trace.jsonl (a JSON object with kind='header')."""

    kind: str = "header"
    schema_version: str = SCHEMA_VERSION
    state_names: list[str]
    action_names: list[str]
    fps: float
    provenance: Provenance


class RecordingSummary(_M):
    video_relpath: str | None = None
    trace_relpath: str | None = None
    frames_expected: int = 0
    frames_written: int = 0
    trace_rows: int = 0
    fps: float = 0.0
    completeness: float = 0.0  # frames_written / frames_expected, measured not assumed
    video_kind: str = "rendered_simulator_frames"  # or "physical_camera"


# --------------------------------------------------------------------------- QA


class QAFlag(_M):
    code: QACode
    severity: Severity
    message: str  # actionable: says what is wrong and what to do
    subject: str = ""  # trial_id or artifact relpath
    evidence: dict[str, Any] = Field(default_factory=dict)


class QAReport(_M):
    subject: str
    flags: list[QAFlag] = Field(default_factory=list)
    accepted: bool = True  # demonstration acceptance rubric verdict
    rejection_reasons: list[str] = Field(default_factory=list)
    quarantined: list[str] = Field(default_factory=list)  # relpaths moved aside (copies kept)

    @property
    def quality(self) -> RecordingQuality:
        if any(f.severity == Severity.ERROR for f in self.flags):
            return RecordingQuality.FAIL
        return RecordingQuality.FLAGGED if self.flags else RecordingQuality.PASS


class FaultResult(_M):
    case_id: str  # e.g. "F01_missing_video"
    description: str
    expected_code: QACode
    detected: bool
    detected_codes: list[str] = Field(default_factory=list)
    message: str = ""  # the actionable error/flag text produced
    evidence_preserved: bool = False
    misleading_success_prevented: bool = False
    executed_at: datetime
    details: dict[str, Any] = Field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.detected and self.evidence_preserved and self.misleading_success_prevented


# --------------------------------------------------------------------------- manifest


class TrialManifestEntry(_M):
    """One row of manifest.json. Covers EVERY planned trial, attempted or not."""

    trial_id: str
    state: TrialState
    task_outcome: TaskOutcome
    termination_reason: TerminationReason
    recording_quality: RecordingQuality
    intervention: Intervention
    condition_name: str
    controller_id: str
    controller_type: ControllerType
    controller_config_hash: str
    model_artifact_sha256: str | None
    seed: int
    duration_s: float | None
    provenance: Provenance
    artifacts: list[ArtifactRef] = Field(default_factory=list)  # video/log/trace/model refs
    calibration_ref: str | None = None  # required ONLY for physical_hardware


class RunManifest(_M):
    schema_version: str = SCHEMA_VERSION
    session_id: str
    provenance: Provenance
    backend: str
    task_id: str
    rubric_version: str
    git_commit: str | None
    software: dict[str, str]
    eval_config_hash: str | None
    created_at: datetime
    trials: list[TrialManifestEntry]


# Required (non-null) TrialManifestEntry fields per provenance. Simulation/mock never require
# physical calibration. Hardware additionally requires a calibration reference.
COMMON_REQUIRED = (
    "trial_id", "state", "task_outcome", "termination_reason", "recording_quality", "intervention",
    "condition_name", "controller_id", "controller_type", "controller_config_hash", "seed", "provenance",
)
REQUIRED_FIELDS_BY_PROVENANCE: dict[Provenance, tuple[str, ...]] = {
    Provenance.MOCK: COMMON_REQUIRED,
    Provenance.SIMULATION: COMMON_REQUIRED,
    Provenance.IMPORTED_REAL_RECORDING: COMMON_REQUIRED,
    Provenance.PHYSICAL_HARDWARE: (*COMMON_REQUIRED, "calibration_ref"),
}
# Fields additionally required once a trial reached a terminal state after running.
REQUIRED_IF_ATTEMPTED = ("duration_s",)
# Learned controllers additionally require model_artifact_sha256 and a MODEL artifact.
