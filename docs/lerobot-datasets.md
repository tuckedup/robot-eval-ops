# LeRobot dataset support and imported-data QA

Audit findings A2 and A3. Everything here is about *imported* recordings: demonstrations the owner of this
repository did **not** collect.

## Formats and versions

| format | declared `codebase_version` | per-episode metadata | data | video | status |
|---|---|---|---|---|---|
| v3.0 | `v3.0` | `meta/episodes/chunk-*/file-*.parquet` | `data/chunk-*/file-*.parquet`, many episodes per shard | `videos/<camera>/chunk-*/file-*.mp4`, many episodes per file | supported, tested on a real public dataset |
| v2.0 / v2.1 | `v2.0`, `v2.1` | `meta/episodes.jsonl` | one parquet per episode | one mp4 per episode and camera | supported (authentic-layout fixtures only) |
| anything else | e.g. `v1.6`, `v9.9` | n/a | n/a | n/a | **rejected** with an explicit reason |

The v3 layout was checked against the installed `lerobot==0.4.4` writer (`lerobot/datasets/utils.py`,
`lerobot_dataset.py`: columns `data/chunk_index`, `data/file_index`, `dataset_from_index`, `dataset_to_index`,
`videos/<camera>/{chunk_index,file_index,from_timestamp,to_timestamp}`) and against the official page
<https://huggingface.co/docs/lerobot/lerobot-dataset-v3> (episode boundaries are resolved through metadata, not
file names; many episodes share one parquet/mp4). A missing `codebase_version` is *inferred* from which metadata
exists, disclosed in `notes`, and the result can never be better than `incomplete`.

**Episode ids are the dataset's actual ids.** They need not be `0..n-1`; nothing in this repository fabricates
`range(total_episodes)`. A requested episode that is not in the metadata is an error, and `episode_to_trace`
refuses it (no file written).

## What "accepted" means

`qa_lerobot_dataset` returns `status`:

* `rejected` – at least one error. `accepted_episodes` still lists episodes with no error of their own, so the
  clean ones are usable and the bad ones come with actionable reasons.
* `incomplete` – nothing failed but a criterion could not be verified (no pyarrow, no decoder, decode budget
  exceeded, version inferred, **no camera features**). Never reported as accepted.
* `accepted` – every criterion ran and passed, including cameras (the video-backed demonstration rubric).
* `accepted_state_only` – only with explicit `require_video=False`; never `accepted`.

Criteria (each `pass` / `fail` / `skipped` in the report):
`layout_supported`, `info_valid`, `episode_metadata`, `data_readable`, `state_action_schema`, `values_finite`,
`timestamps`, `frame_consistency`, `index_continuity`, `video_present`, `video_decodable`, `video_alignment`.

Concretely: `action` and `observation.state` exist and are uniform finite numeric vectors of the declared width;
timestamps are finite, strictly increasing within an episode and spaced within 50% of `1/fps`; `frame_index` is
`0..n-1`; row count equals the declared length; the global `index` equals the episode's
`dataset_from_index..dataset_to_index` slice and those ranges are contiguous across episodes and shard
boundaries; each episode × camera video exists, **decodes**, its `[from_timestamp, to_timestamp)` window lies
inside the file and holds `length ± 1` frames starting at the expected time.

Only the selected episodes' rows and frames are read when `episodes=[...]` is given (tested: a defect in
another episode does not affect the verdict).

## Import record

`robotevalops robot import-dataset --path P --out D --source-url U --source-revision R --license L` writes
`D/import_record.json`: source, revision and licence as supplied, a size bound check (`--max-mb`, default 500),
SHA-256 of every file, the tested LeRobot version, the full QA report, and a whole-episode train/eval split over
the **accepted** actual ids. Exit codes: 0 accepted, 1 rejected, 3 incomplete.

## Tested versions and platforms

Python 3.11, Windows 11, `lerobot==0.4.4`, `pyarrow 25.0.1`, `av` (PyAV) for decoding. `uv.lock` also resolves
`lerobot 0.6.1` for Python 3.12; that combination was **not** tested, and moving commands refuse any LeRobot
version outside `TESTED_LEROBOT_VERSIONS` (`adapters/lerobot_wrapper.py`). Linux was not exercised by hand;
CI/Docker are unexecuted (see `docs/verification.md`).
