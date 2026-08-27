#!/bin/bash
echo ""
echo "==================================================="
echo "  MediTrack - Emergency Medical Record System"
echo "==================================================="
echo ""

if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 is not installed!"
    echo "Install it from: https://www.python.org/downloads/"
    exit 1
fi

echo "Python found!"
echo ""

if [ ! -d "venv" ]; then
    echo "No virtual environment found — creating one (first run only)..."
    python3 -m venv venv
fi

source venv/bin/activate

echo "Installing required packages..."
pip install -r requirements.txt --quiet

echo "Starting MediTrack..."
echo "Open your browser at: http://localhost:5000"
echo ""
echo "Press CTRL+C to stop."
echo ""

python run.py
