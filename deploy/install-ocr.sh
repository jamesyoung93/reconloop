#!/usr/bin/env bash
# Classic Linux cluster init script: OS packages only. Use platform library
# settings for Python dependencies. Pin versions available for your runtime OS.
set -euo pipefail
: "${RECONLOOP_TESSERACT_VERSION:?Set an approved apt version for tesseract-ocr}"
: "${RECONLOOP_TESSERACT_ENG_VERSION:?Set an approved apt version for tesseract-ocr-eng}"
if [[ "$(id -u)" != "0" ]]; then
  echo "Run as a cluster init script with package-install privileges." >&2
  exit 1
fi
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  "tesseract-ocr=${RECONLOOP_TESSERACT_VERSION}" \
  "tesseract-ocr-eng=${RECONLOOP_TESSERACT_ENG_VERSION}"
tesseract --version
tesseract --list-langs
