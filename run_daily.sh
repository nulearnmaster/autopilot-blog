#!/bin/bash
set -e
cd "$(dirname "$0")"
python3 generate.py
python3 build.py
