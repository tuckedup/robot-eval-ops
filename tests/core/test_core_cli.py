from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest
import yaml
from conftest import FakeAdapter, NoopController
from typer.testing import CliRunner

from robotevalops.cli.session_cmds import app
from robotevalops.core.service import EvalService
from robotevalops.schemas import Provenance, RecordingQuality, SessionState, TrialState

runner = CliRunner()

CFG = {
    "name": "cli",
    "provenance": "mock",
    "backend": "mock",
    "trials_per_condition": 2,
    "controllers": [
        {"controller_id": "a", "type": "scripted", "version": "1"},
        {"controller_id": "b", "type": "scripted", "version": "1"},
    ],
    "conditions": [{"name": "n1", "kind": "nominal"}, {"name": "n2", "kind": "nominal"}],
}


@pytest.fixture
def home(tmp_path: Path) -> str:
    return str(tmp_path / "home")


@pytest.fixture
def cfg_path(tmp_path: Path) -> str:
    p = tmp_path / "eval.yaml"
    p.write_text(yaml.safe_dump(CFG), encoding="utf-8")
    return str(p)


def call(*args: str, ok: bool = True):
    res = runner.invoke(app, list(args))
    if ok:
        assert res.exit_code == 0, res.output
    return res


def create_planned(home: str, cfg_path: str) -> str:
    out = json.loads(call("create", "--name", "n", "--config", cfg_path, "--home", home, "--json").output)
    sid = out["session_id"]
    plan = json.loads(call("plan", sid, "--home", home, "--json").output)
    assert plan["planned"] == 8  # 2 controllers x 2 conditions x 2 trials
    return sid


@pytest.fixture
def fake_registry(monkeypatch):
    mod = types.ModuleType("robotevalops.adapters.registry")
    mod.adapters = []

    def get_adapter(backend, session):
        a = FakeAdapter()
        mod.adapters.append(a)
        return a

    mod.get_adapter = get_adapter
    mod.get_controller = lambda spec, backend: NoopController(spec)
    monkeypatch.setitem(sys.modules, "robotevalops.adapters.registry", mod)
    return mod


def test_create_plan_list_show_export(home, cfg_path, tmp_path):
    sid = create_planned(home, cfg_path)
    rows = json.loads(call("list", "--home", home, "--json").output)
    assert [r["session_id"] for r in rows] == [sid] and rows[0]["planned_total"] == 8
    shown = json.loads(call("show", sid, "--trials", "--home", home, "--json").output)
    assert shown["trial_counts"]["planned"] == 8 and len(shown["trials"]) == 8
    assert sid in call("show", sid, "--home", home).output
    out = tmp_path / "m.json"
    call("export-manifest", sid, "--out", str(out), "--home", home)
    manifest = json.loads(out.read_text(encoding="utf-8"))
    assert len(manifest["trials"]) == 8 and manifest["provenance"] == "mock"
    stdout_manifest = json.loads(call("export-manifest", sid, "--home", home).output)
    assert len(stdout_manifest["trials"]) == 8


def test_create_requires_provenance_and_backend_without_config(home):
    res = call("create", "--name", "x", "--home", home, ok=False)
    assert res.exit_code == 1


def test_unknown_session_gives_json_error_and_nonzero_exit(home):
    res = call("show", "nope", "--home", home, "--json", ok=False)
    assert res.exit_code == 1
    assert json.loads(res.output)["error"] == "NotFoundError"


def test_stop_ack_and_recover(home, cfg_path):
    sid = create_planned(home, cfg_path)
    first = json.loads(call("stop", sid, "--home", home, "--json").output)
    second = json.loads(call("stop", sid, "--home", home, "--json").output)
    assert first["first_request"] is True and second["first_request"] is False
    ack = json.loads(call("ack", sid, "--operator", "alice", "--home", home, "--json").output)
    assert ack["operator_ack_at"] and ack["operator"] == "alice"
    assert json.loads(call("recover", "--home", home, "--json").output) == {}


def test_run_with_registry_completes_session(home, cfg_path, fake_registry):
    sid = create_planned(home, cfg_path)
    pf = json.loads(call("preflight", sid, "--home", home, "--json").output)
    assert pf["ok"] is True
    out = json.loads(call("run", sid, "--home", home, "--json").output)
    assert out["final_state"] == "completed" and out["trials_processed"] == 8
    svc = EvalService(home)
    assert svc.get_session(sid).state == SessionState.COMPLETED
    assert len(svc.list_trials(sid, TrialState.COMPLETED)) == 8


def test_run_without_preflight_on_mock_still_checks_each_trial(home, cfg_path, fake_registry):
    sid = create_planned(home, cfg_path)
    out = json.loads(call("run", sid, "--max-trials", "3", "--home", home, "--json").output)
    assert out["trials_processed"] == 3 and out["final_state"] == "ready"


def test_run_refuses_hardware_without_ack(home, fake_registry):
    svc = EvalService(home)
    s = svc.create_session("hw", Provenance.PHYSICAL_HARDWARE, "so101_lerobot", device_id="arm0")
    res = call("run", s.session_id, "--home", home, "--json", ok=False)
    assert res.exit_code == 1
    assert json.loads(res.output)["error"] == "HardwareRefusedError"
    assert fake_registry.adapters == []  # no adapter was even constructed


def test_run_refuses_when_fresh_preflight_required(home, cfg_path, fake_registry):
    sid = create_planned(home, cfg_path)
    EvalService(home).flag_fresh_preflight(sid)
    res = call("run", sid, "--home", home, "--json", ok=False)
    assert json.loads(res.output)["error"] == "PreflightFailedError"


def test_run_without_registry_gives_capability_error(home, cfg_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "robotevalops.adapters.registry", None)  # makes the import fail
    sid = create_planned(home, cfg_path)
    res = call("run", sid, "--home", home, "--json", ok=False)
    assert res.exit_code == 1
    body = json.loads(res.output)
    assert body["error"] == "CapabilityUnavailableError" and "registry" in body["message"]


def test_preflight_failure_exits_2(home, cfg_path, monkeypatch):
    mod = types.ModuleType("robotevalops.adapters.registry")
    mod.get_adapter = lambda backend, session: FakeAdapter(preflight_ok=False)
    mod.get_controller = lambda spec, backend: NoopController(spec)
    monkeypatch.setitem(sys.modules, "robotevalops.adapters.registry", mod)
    sid = create_planned(home, cfg_path)
    res = call("preflight", sid, "--home", home, "--json", ok=False)
    assert res.exit_code == 2 and json.loads(res.output)["ok"] is False
    assert EvalService(home).get_session(sid).state == SessionState.PREFLIGHT


def test_run_always_applies_qa_and_writes_manifest(home, cfg_path, fake_registry):
    sid = create_planned(home, cfg_path)
    call("run", sid, "--home", home, "--json")
    svc = EvalService(home)
    trials = svc.list_trials(sid)
    attempted = [t for t in trials if t.is_attempted]
    assert len(attempted) == 8
    assert all(t.recording_quality != RecordingQuality.UNCHECKED for t in attempted)
    # the fake adapter writes a 16-byte "video": QA must have caught it, not left it unchecked
    assert all(not t.is_autonomous_success for t in attempted)
    assert (svc.run_dir(sid) / "manifest.json").is_file()
    assert (svc.run_dir(sid) / "qa" / f"{trials[0].trial_id}.qa.json").is_file()


def test_export_manifest_writes_run_dir_manifest(home, cfg_path):
    sid = create_planned(home, cfg_path)
    call("export-manifest", sid, "--home", home)
    path = EvalService(home).run_dir(sid) / "manifest.json"
    assert len(json.loads(path.read_text(encoding="utf-8"))["trials"]) == 8
