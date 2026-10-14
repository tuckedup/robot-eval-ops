#!/usr/bin/env bash
# Build the wheel, install it NON-editable into a fresh venv, and run the default mock demo from an unrelated
# directory. Exit 0 only if the installed package works without the checkout. Usage: scripts/verify_wheel.sh
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
uv build --wheel --out-dir "$work/dist" "$here"
uv venv --python 3.11 "$work/venv"
uv pip install --python "$work/venv/bin/python" "$work"/dist/*.whl 2>/dev/null \
  || uv pip install --python "$work/venv/Scripts/python.exe" "$work"/dist/*.whl
mkdir "$work/elsewhere" && cd "$work/elsewhere"
export ROBOTEVALOPS_HOME="$work/home"
exe="$work/venv/bin/robotevalops"; [ -x "$exe" ] || exe="$work/venv/Scripts/robotevalops.exe"
"$exe" demo run --skip-faults --home "$work/demo" --out "$work/out"
echo "wheel demo OK from $(pwd)"
