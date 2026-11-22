#!/bin/bash
export PATH="$HOME/.local/bin:/usr/local/bin:$PATH"   # so the app can find `gh`
cd "$(dirname "$(readlink -f "$0")")" || exit 1
exec ./venv/bin/python gist_mover.py >> "$HOME/.cache/gist_mover.log" 2>&1
