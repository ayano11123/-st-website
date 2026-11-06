#!/usr/bin/env bash
# Simple launcher for your own computer: ./run.sh
cd "$(dirname "$0")"
python3 -m pip install -r requirements.txt
python3 app.py
