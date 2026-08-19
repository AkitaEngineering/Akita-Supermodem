#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

echo "==> Tests"
python -m pytest tests/ -q

echo "==> Lint"
python -m flake8 akita_supermodem/ examples/ tests/ --max-line-length=120 --jobs=1

echo "==> Compile"
python -m compileall -q akita_supermodem tests

echo "==> Package"
python -m pip install --quiet build
python -m build

echo "==> Artifacts"
ls -l dist
echo "Release rehearsal complete."
