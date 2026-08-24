#!/bin/bash
cd "$(dirname "$0")"
INTERVAL=${1:-14400}
while true; do
  python3 generate.py || true
  python3 build.py || true
  sleep "$INTERVAL"
done
