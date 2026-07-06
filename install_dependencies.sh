#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "Checking Python..."
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required but was not found."
  echo "Install Python 3.11+ first, then rerun this script."
  exit 1
fi

echo "Using $(python3 --version)"

echo "Upgrading pip..."
python3 -m pip install --upgrade pip

echo "Installing Python libraries..."
python3 -m pip install -r requirements.txt

echo "Checking Tesseract OCR..."
if ! command -v tesseract >/dev/null 2>&1; then
  echo ""
  echo "Python libraries are installed, but the Tesseract system app is missing."
  echo "OCR for scanned PDFs needs it."
  echo ""
  echo "On macOS with Homebrew, install it with:"
  echo "  brew install tesseract"
  echo ""
else
  echo "Found Tesseract: $(tesseract --version | head -n 1)"
fi

echo ""
echo "Done. You can test the project with:"
echo "  python3 -B -m unittest discover -s tests"
echo ""
echo "Run the app with:"
echo "  python3 -m docusplit process --input inbox --output organized --config config.yaml"
