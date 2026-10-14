#!/usr/bin/env bash
# Regenerate verification evidence from the CURRENT commit. Writes docs/verification-run.json.
set -u
cd "$(dirname "$0")/.."
PY=.venv/Scripts/python.exe; [ -x "$PY" ] || PY=.venv/bin/python
out=docs/verification-run.json; tmp=$(mktemp -d)
commit=$(git rev-parse HEAD); dirty=$(git status --porcelain | grep -v '^??' | wc -l)
run() { name=$1; shift; s=$(date +%s); "$@" > "$tmp/$name.log" 2>&1; rc=$?; e=$(date +%s); echo "$name rc=$rc $((e-s))s: $(tail -1 "$tmp/$name.log")"; echo "{\"name\":\"$name\",\"rc\":$rc,\"seconds\":$((e-s)),\"last_line\":$($PY -c 'import json,sys;print(json.dumps(sys.stdin.read().strip()))' < <(tail -1 "$tmp/$name.log"))}" >> "$tmp/results.jsonl"; }
run ruff_check $PY -m ruff check .
run ruff_format $PY -m ruff format --check .
run mypy $PY -m mypy src
for d in core data eval robotics verification; do
  run "pytest_$d" $PY -m pytest -q -p no:cacheprovider tests/$d -m "not physics and not s3_real and not hardware" -rs
done
run pytest_physics $PY -m pytest -q -p no:cacheprovider -m physics tests -rs
$PY - "$tmp" "$commit" "$dirty" > "$out" <<'PY'
import json, sys, platform, importlib.metadata as m
tmp, commit, dirty = sys.argv[1:4]
rows = [json.loads(l) for l in open(f"{tmp}/results.jsonl")]
skips = {}
import re, glob
for f in glob.glob(f"{tmp}/pytest_*.log"):
    skips[f.split("/")[-1][:-4].split("\\")[-1]] = re.findall(r"SKIPPED \[\d+\] (.*)", open(f, errors="replace").read())
print(json.dumps({"commit": commit, "uncommitted_tracked_changes": int(dirty), "python": platform.python_version(),
  "platform": platform.platform(), "lerobot": m.version("lerobot"), "pybullet": m.version("pybullet"),
  "results": rows, "skips": skips}, indent=2))
PY
echo "wrote $out"
