# 90-second operator demo (executed, simulation)

Run it: `robotevalops demo operator --home data/operator_demo --out docs/demo/operator` (about 2 minutes on a
slow laptop CPU; needs the `sim` extra). Every step is real: simulator evidence decides success and failure, the
corruption truncates a recorded video, the interruption kills a runner process. Result of the executed run:
`docs/demo/operator/operator-demo-summary.json`; report screenshot: `docs/demo/screenshots/report_operator_demo.png`.

| time | step | what the operator sees (from the executed run) |
|---|---|---|
| 0:00 | **Preflight** | pybullet import, Panda URDF, TinyRenderer frame, video encoder: all `ok`. A failing check refuses the run. |
| 0:10 | **One verified success** | `scripted_baseline_a`, `stress_nominal`: success decided from physics evidence (block fully in target, released, 2 s dwell); recording QA `pass`, so it counts as a *verified* autonomous success. |
| 0:25 | **One physics task failure** | `scripted_baseline_b` with a 2.0 kg block: `placement: block not entirely inside target`, `dwell not held`. Recorded as a task failure with its video, not hidden and not an infrastructure error. |
| 0:40 | **One corrupt recording rejected** | A successful trial's video is truncated. Re-validation: `truncated_video` + `hash_mismatch`, recording quality `fail`. The raw task outcome (`success`) stays visible, but it is **not** a verified success and is excluded from `evaluable`. |
| 0:55 | **Interrupted and recovered** | The runner is killed mid-trial. `session recover`: the running trial becomes `aborted / interrupted_runner / unscored`, the session returns to `preflight` and requires a fresh preflight, partial files are kept, nothing is marked success. |
| 1:10 | **Verified artifact transfer** | Session packaged into a local store and downloaded back: 18 artifacts, every SHA-256 `verified`. |
| 1:20 | **Report** | `report.html/md/csv/json`: denominators (planned/attempted/evaluable), Wilson intervals, provenance banner "SIMULATION, not the SO-101 and not hardware". |

Scope: simulation, scripted controllers. Not a robot, not a learned policy, not hardware operation.
