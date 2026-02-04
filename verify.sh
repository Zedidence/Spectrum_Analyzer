#!/bin/bash
#
# Verification Script for Spectrum Analyzer
# Checks system requirements and configuration
#

echo "════════════════════════════════════════════════════════════════════"
echo "SPECTRUM ANALYZER - System Verification"
echo "════════════════════════════════════════════════════════════════════"
echo ""

ERRORS=0
WARNINGS=0

# Function to print status
print_status() {
    if [ $1 -eq 0 ]; then
        echo "✓ $2"
    else
        echo "✗ $2"
        ERRORS=$((ERRORS + 1))
    fi
}

print_warning() {
    echo "⚠ $1"
    WARNINGS=$((WARNINGS + 1))
}

# Check Python version
echo "Checking Python..."
python3 --version &>/dev/null
print_status $? "Python 3 installed"

# Check BladeRF
echo ""
echo "Checking BladeRF..."
if lsusb | grep -q "Nuand"; then
    echo "✓ BladeRF detected on USB"
    lsusb | grep "Nuand"
else
    print_warning "BladeRF not detected on USB - is it connected?"
fi

bladeRF-cli -p &>/dev/null
print_status $? "bladeRF-cli can access device"

# Check Python packages
echo ""
echo "Checking Python packages..."
python3 -c "import flask" 2>/dev/null
print_status $? "Flask installed"

python3 -c "import flask_socketio" 2>/dev/null
print_status $? "Flask-SocketIO installed"

python3 -c "import numpy" 2>/dev/null
print_status $? "NumPy installed"

python3 -c "import pyfftw" 2>/dev/null
print_status $? "pyFFTW installed"

python3 -c "from gnuradio import gr" 2>/dev/null
print_status $? "GNU Radio installed"

python3 -c "from osmosdr import source" 2>/dev/null
print_status $? "gr-osmosdr installed"

# Check project files
echo ""
echo "Checking project files..."
cd "$(dirname "$0")"

[ -f "backend/app.py" ]
print_status $? "backend/app.py exists"

[ -f "backend/bladerf_interface.py" ]
print_status $? "backend/bladerf_interface.py exists"

[ -f "backend/signal_processor.py" ]
print_status $? "backend/signal_processor.py exists"

[ -f "static/index.html" ]
print_status $? "static/index.html exists"

[ -f "static/js/app.js" ]
print_status $? "static/js/app.js exists"

# Test imports
echo ""
echo "Testing Python imports..."
python3 -c "
import sys
sys.path.insert(0, 'backend')
from bladerf_interface import BladeRFInterface
from signal_processor import SignalProcessor
print('✓ All Python modules import successfully')
" 2>&1

# Check network
echo ""
echo "Checking network..."
HOSTNAME=$(hostname)
LOCAL_IP=$(hostname -I | awk '{print $1}')
echo "  Hostname: $HOSTNAME"
echo "  Local IP: $LOCAL_IP"
echo "  Access URLs:"
echo "    Local:   http://localhost:5000"
echo "    Network: http://$LOCAL_IP:5000"

# Port check
if command -v netstat &>/dev/null; then
    if netstat -tulpn 2>/dev/null | grep -q ":5000 "; then
        print_warning "Port 5000 is already in use"
    else
        echo "✓ Port 5000 is available"
    fi
fi

# Summary
echo ""
echo "════════════════════════════════════════════════════════════════════"
if [ $ERRORS -eq 0 ]; then
    echo "✓ System verification passed!"
    if [ $WARNINGS -gt 0 ]; then
        echo "  $WARNINGS warning(s) - check above"
    fi
    echo ""
    echo "Ready to start:"
    echo "  ./run.sh"
else
    echo "✗ System verification failed with $ERRORS error(s)"
    echo ""
    echo "Please fix the errors above before starting."
fi
echo "════════════════════════════════════════════════════════════════════"
