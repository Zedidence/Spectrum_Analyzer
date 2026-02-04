# Troubleshooting Guide

This guide helps diagnose and fix common issues with the Spectrum Analyzer.

## Table of Contents
- [No Visual Display](#no-visual-display)
- [Connection Issues](#connection-issues)
- [BladeRF Problems](#bladerf-problems)
- [Performance Issues](#performance-issues)
- [Debugging Tools](#debugging-tools)

---

## No Visual Display

### Symptoms
- Blank spectrum/waterfall displays
- "Waiting for data..." message persists
- No error messages

### Diagnosis Steps

#### 1. Check Browser Console
Open browser developer console (F12) and look for:

**Good signs:**
```
✓ WebSocket connected successfully
✓ First FFT data packet received!
✓ SpectrumDisplay: First data received
✓ WaterfallDisplay: First line added
```

**Bad signs:**
```
⚠ Data timeout #X - no IQ samples received
✗ Queue is empty - no data being received!
✗ WebSocket disconnected
```

#### 2. Check Backend Logs
Look at the server terminal output for:

**Good flow:**
```
✓ BladeRF setup complete - ready to stream
✓ Flowgraph running - data should be flowing
✓ First IQ data received - processing pipeline active
📊 Stats: Update rate = 15.0 Hz
```

**Problem indicators:**
```
✗ Failed to setup BladeRF
⚠ Queue is empty - no data being received!
⚠ Data timeout - no IQ samples received
```

### Common Causes & Solutions

#### Cause 1: BladeRF Not Connected
**Symptoms:** Backend shows "Failed to setup BladeRF"

**Solution:**
```bash
# Check USB connection
lsusb | grep Nuand

# Verify device detection
bladeRF-cli -p

# Check permissions
ls -l /dev/bus/usb/*/$(lsusb | grep Nuand | awk '{print $4}' | tr -d ':')

# If permission denied, add user to plugdev group
sudo usermod -a -G plugdev $USER
# Then logout and login again
```

#### Cause 2: GNU Radio Flowgraph Not Starting
**Symptoms:** Backend shows "Flowgraph started" but queue remains empty

**Solution:**
```bash
# Test BladeRF with simple GNU Radio script
python3 -c "
from osmosdr import source
from gnuradio import gr

tb = gr.top_block()
src = source('bladerf=0')
src.set_sample_rate(2.4e6)
src.set_center_freq(100e6)
print('BladeRF source created successfully')
"
```

#### Cause 3: Incorrect Sample Rate
**Symptoms:** Backend runs but no data flows

**Solution:** Edit `backend/app.py` and adjust sample rate:
```python
# Try different sample rates
sample_rate = 1e6    # 1 MS/s (conservative)
sample_rate = 2e6    # 2 MS/s
sample_rate = 2.4e6  # 2.4 MS/s (default)
```

#### Cause 4: Canvas Not Rendering
**Symptoms:** Data is received but displays are blank

**Solution:**
```javascript
// Check browser console for canvas errors
// Verify canvas elements exist:
console.log(document.getElementById('spectrum-canvas'));
console.log(document.getElementById('waterfall-canvas'));

// Should output: <canvas id="..."> elements, not null
```

---

## Connection Issues

### WebSocket Disconnects Briefly

**Symptoms:** Connection indicator flickers, brief disconnection messages

**Causes:**
1. Network latency or congestion
2. Browser tab inactive (Chrome throttling)
3. Server overload

**Solutions:**
```javascript
// Increase reconnection attempts in static/js/app.js
socket = io({
    reconnection: true,
    reconnectionDelay: 1000,
    reconnectionAttempts: 20  // Increased from 10
});
```

### Cannot Connect from Remote Device

**Symptoms:** Works on localhost but not from other devices

**Solutions:**
```bash
# 1. Check firewall
sudo ufw status
sudo ufw allow 5000

# 2. Verify server is listening on all interfaces
netstat -tulpn | grep 5000
# Should show: 0.0.0.0:5000 (not 127.0.0.1:5000)

# 3. Get Raspberry Pi IP address
hostname -I

# 4. Try accessing from remote device:
# http://[raspberry-pi-ip]:5000
```

---

## BladeRF Problems

### Device Not Detected

**Check USB Connection:**
```bash
# Verify BladeRF appears in USB devices
lsusb | grep -i nuand

# Expected output:
# Bus 002 Device 003: ID 2cf0:5250 Nuand LLC bladeRF 2.0 micro
```

### Device Opens But No Data

**Check Firmware:**
```bash
bladeRF-cli -i
# Look for firmware version in output
# Should be 2.6.0 or newer
```

**Test with bladeRF-cli:**
```bash
bladeRF-cli -i
> set frequency rx 100M
> set samplerate rx 2.4M
> set bandwidth rx 2M
> set gain rx 40
> rx config file=/tmp/test.sc16q11 format=bin n=100000
> rx start
> rx wait
> quit

# Check if file was created
ls -lh /tmp/test.sc16q11
# Should be ~800 KB (400K IQ samples * 4 bytes)
```

### Gain Too Low - No Signals Visible

**Increase Gain:**
- In web UI, move gain slider to 50-60 dB
- Or edit `backend/bladerf_interface.py`:
```python
self.gain = 50  # Changed from 40
```

---

## Performance Issues

### Low Update Rate (<5 Hz)

**Causes:**
1. CPU overloaded
2. FFT size too large
3. Too much averaging

**Solutions:**
```python
# In backend/app.py, reduce FFT size and averaging:
fft_size = 1024      # Reduced from 2048
averaging = 2        # Reduced from 4
```

### High CPU Usage (>80%)

**Solutions:**
```python
# Reduce sample rate in backend/app.py:
sample_rate = 1e6    # 1 MS/s instead of 2.4 MS/s

# Reduce update rate in backend/app.py:
time.sleep(0.1)      # 10 Hz instead of 15 Hz
```

### Waterfall Stuttering

**Solutions:**
```javascript
// Reduce waterfall history in static/js/app.js:
waterfallDisplay = new WaterfallDisplay('waterfall-canvas', 250);
// Reduced from 500 lines
```

---

## Debugging Tools

### Enable Maximum Logging

**Backend:**
```python
# In backend/app.py and backend/bladerf_interface.py
# Already set to DEBUG level

# View logs:
python3 backend/app.py 2>&1 | tee debug.log
```

**Frontend:**
```javascript
// Browser console (F12) automatically shows all logs
// Filter by severity:
// - Green: console.log (info)
// - Yellow: console.warn (warnings)
// - Red: console.error (errors)
```

### Test Components Individually

**Test 1: BladeRF Hardware**
```bash
bladeRF-cli -p  # Probe device
```

**Test 2: Python Imports**
```bash
python3 -c "
from backend.bladerf_interface import BladeRFInterface
from backend.signal_processor import SignalProcessor
print('✓ Imports successful')
"
```

**Test 3: FFT Processing**
```bash
python3 -c "
import numpy as np
from backend.signal_processor import SignalProcessor

proc = SignalProcessor(fft_size=2048, sample_rate=2.4e6)
iq = np.random.randn(2048) + 1j * np.random.randn(2048)
spectrum = proc.process_iq_samples(iq)
print(f'✓ FFT processing works: {len(spectrum)} bins')
"
```

### Check Browser Compatibility

**Recommended Browsers:**
- Chrome/Chromium 90+
- Firefox 88+
- Safari 14+ (macOS/iOS)

**Known Issues:**
- Internet Explorer: Not supported
- Old Android browsers: May have Canvas performance issues

### Monitor System Resources

```bash
# CPU usage
htop

# Memory usage
free -h

# USB bandwidth (if using external tool)
lsusb -t
```

---

## Getting Help

If problems persist after trying these solutions:

1. **Collect Logs:**
   ```bash
   # Backend logs
   python3 backend/app.py 2>&1 | tee backend.log

   # Browser console logs (F12, save as file)
   ```

2. **System Info:**
   ```bash
   # OS version
   cat /etc/os-release

   # Python version
   python3 --version

   # GNU Radio version
   gnuradio-config-info --version

   # BladeRF firmware
   bladeRF-cli -i
   ```

3. **Create Issue:**
   - Include logs (backend.log and browser console)
   - Include system info
   - Describe what you expected vs what happened
   - Steps to reproduce

---

## Quick Checklist

Before reporting an issue, verify:

- [ ] BladeRF detected: `lsusb | grep Nuand` shows device
- [ ] Permissions OK: `bladeRF-cli -p` works without sudo
- [ ] Backend starts: No errors when running `python3 backend/app.py`
- [ ] Browser console: No red errors (open with F12)
- [ ] Firewall open: `sudo ufw allow 5000` if accessing remotely
- [ ] Gain sufficient: Try 50-60 dB if no signals visible
- [ ] Frequency correct: 88-108 MHz for FM radio, 2400 MHz for WiFi
- [ ] Antenna connected: Check physical connections

---

**Version:** 1.0.1
**Last Updated:** 2026-02-04
