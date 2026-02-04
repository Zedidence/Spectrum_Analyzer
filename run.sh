#!/bin/bash
#
# Launch script for Spectrum Analyzer
#

cd "$(dirname "$0")"

echo "Starting Spectrum Analyzer..."
echo "Access the web interface at: http://$(hostname -I | awk '{print $1}'):5000"
echo "Or locally at: http://localhost:5000"
echo ""

python3 backend/app.py
