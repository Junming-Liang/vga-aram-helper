#!/bin/sh
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
  echo 'Please follow OCR_SETUP.md to create .venv and install optional dependencies.' >&2
  exit 1
fi
exec .venv/bin/python server.py --enable-ocr "$@"
