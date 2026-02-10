# Troubleshooting Guide

This guide helps diagnose and fix common issues with the Spectrum Analyzer v2.0.

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
- No data flowing after clicking Start

### Diagnosis Steps

#### 1. Check Browser Console (F12)

**Good signs:**
```
[Connection] WebSocket connected
[Protocol] Frame received, type=1, 8256 bytes
```

**Bad signs:**
```
WebSocket connection failed
WebSocket closed unexpectedly
```

#### 2. Check Backend Logs

```bash
# Watch main log
tail -f logs/app.log

# Or run with debug
python3 backend/main.py --debug
```

**Good flow:**
```
Starting stream: 100.0 MHz, 2.0 MS/s, gain 40.0 dB
GNU Radio flowgraph started
DSP thread started
Broadcast loop started
```

**Problem indicators:**
```
Failed to initialize BladeRF
IQ queue full, dropping data
DSP thread error
```

### Common Causes & Solutions

#### Cause 1: BladeRF Not Connected

**Solution:**
```bash
# Check USB connection
lsusb | grep Nuand

# Verify device detection
bladeRF-cli -p

# Check permissions
ls -l /dev/bus/usb/*/$(lsusb | grep Nuand | awk '{print $4}' | tr -d ':')

# If permission denied
sudo usermod -a -G plugdev $USER
# Logout and login again
```

#### Cause 2: GNU Radio Not Starting

**Solution:**
```bash
# Test BladeRF with GNU Radio directly
python3 -c "
from osmosdr import source
from gnuradio import gr

tb = gr.top_block()
src = source('bladerf=0')
src.set_sample_rate(2e6)
src.set_center_freq(100e6)
print('BladeRF source created successfully')
"
```

#### Cause 3: Dependencies Missing

**Solution:**
```bash
pip3 install -r requirements.txt

# Verify key imports
python3 -c "import fastapi, uvicorn, numpy, scipy, pyfftw; print('All imports OK')"
```

#### Cause 4: WebGL Context Lost

**Symptoms:** Waterfall stops updating, spectrum still works

**Solution:** Refresh the browser page. WebGL context loss recovery is built in, but a refresh guarantees a clean state.

---

## Connection Issues

### WebSocket Won't Connect

**Symptoms:** Browser shows connection error, no data

**Check server is running:**
```bash
# Verify the process
ps aux | grep main.py

# Check the port
ss -tlnp | grep 5000
# Should show: 0.0.0.0:5000 (listening on all interfaces)
```

### Cannot Connect from Remote Device

**Solutions:**
```bash
# 1. Check firewall
sudo ufw status
sudo ufw allow 5000

# 2. Get Raspberry Pi IP
hostname -I

# 3. Access from remote device:
# http://[raspberry-pi-ip]:5000
```

### WebSocket Disconnects Frequently

**Possible causes:**
1. Network latency or congestion
2. Browser tab inactive (Chrome throttles background tabs)
3. Server overloaded

The WebSocket client has built-in auto-reconnect. If disconnects are frequent, check:
```bash
# Monitor connection log
tail -f logs/streaming/stream.log | grep -i "websocket\|connect\|disconnect"
```

---

## BladeRF Problems

### Device Not Detected

```bash
# Verify BladeRF appears in USB devices
lsusb | grep -i nuand
# Expected: Bus 002 Device 003: ID 2cf0:5250 Nuand LLC bladeRF 2.0 micro

# Probe with bladeRF-cli
bladeRF-cli -p
```

### Device Opens But No Data

**Check firmware:**
```bash
bladeRF-cli -i
# Look for firmware version - should be 2.6.0 or newer
```

**Test with bladeRF-cli:**
```bash
bladeRF-cli -i
> set frequency rx 100M
> set samplerate rx 2M
> set bandwidth rx 2M
> set gain rx 40
> rx config file=/tmp/test.sc16q11 format=bin n=100000
> rx start
> rx wait
> quit

# Check if file was created (~800 KB expected)
ls -lh /tmp/test.sc16q11
```

### No Signals Visible

- Increase gain: use the gain slider in the UI (try 50-60 dB)
- Check antenna is connected
- Verify frequency range: BladeRF 2.0 covers 47 MHz - 6 GHz
- Try FM radio at 88-108 MHz as a known signal source

---

## Performance Issues

### Low Update Rate

**Causes:**
1. FFT size too large
2. Sample rate too high for CPU
3. CPU overloaded by other processes

**Solutions:**
```bash
# Reduce FFT size
python3 backend/main.py --fft-size 1024

# Reduce sample rate
python3 backend/main.py --sample-rate 1e6

# Check CPU usage
htop
```

### High CPU Usage (>50%)

```bash
# Lower settings
python3 backend/main.py --fft-size 1024 --sample-rate 1e6
```

Also in the UI:
- Set averaging mode to "None" (fastest)
- Disable DC removal if not needed
- Disable peak hold if not needed

### Queue Full Warnings

```
IQ queue full, dropping data
```

This means the DSP thread can't process data as fast as it arrives. Solutions:
1. Reduce FFT size (fewer bins to compute)
2. Reduce sample rate (less data per second)
3. Set averaging to "None" mode
4. Close other CPU-intensive applications

### Waterfall Stuttering

- Ensure WebGL is enabled in your browser
- Close other GPU-intensive applications
- Try reducing the browser window size

---

## Debugging Tools

### Enable Debug Logging

```bash
python3 backend/main.py --debug
```

This enables verbose output for all components. Check specific log files:
```bash
tail -f logs/debug.log           # Everything
tail -f logs/hardware/bladerf.log  # Hardware + DSP
tail -f logs/streaming/stream.log  # Streaming + WebSocket
```

### Test Components Individually

**Test 1: BladeRF Hardware**
```bash
bladeRF-cli -p
```

**Test 2: Python Imports**
```bash
python3 -c "
import sys; sys.path.insert(0, 'backend')
from config import Config
from hardware.bladerf_interface import BladeRFInterface
from dsp.pipeline import DSPPipeline
from streaming.manager import StreamManager
print('All imports successful')
"
```

**Test 3: FastAPI App Creation**
```bash
python3 -c "
import sys; sys.path.insert(0, 'backend')
from config import Config
from app import create_app
app = create_app(Config())
print('FastAPI app created successfully')
print('Routes:', [r.path for r in app.routes])
"
```

### Browser Compatibility

**Recommended:**
- Chrome/Chromium 90+ (best WebGL performance)
- Firefox 88+
- Safari 14+

**Required features:**
- WebGL 1.0 (waterfall display)
- ES6 modules (frontend code)
- Native WebSocket (data connection)

### Monitor System Resources

```bash
# CPU and memory usage
htop

# USB bandwidth
lsusb -t

# Disk space (for logs)
df -h
du -sh logs/
```

---

## Getting Help

If problems persist:

1. **Collect Logs:**
   ```bash
   # Backend logs
   python3 backend/main.py --debug 2>&1 | tee backend_debug.log

   # Or check existing logs
   ls -la logs/ logs/hardware/ logs/streaming/
   ```

2. **System Info:**
   ```bash
   cat /etc/os-release
   python3 --version
   gnuradio-config-info --version
   bladeRF-cli -p
   pip3 list | grep -E "fastapi|uvicorn|numpy|scipy|pyfftw"
   ```

3. **Create Issue:**
   - Include logs (debug.log and browser console)
   - Include system info
   - Describe expected vs actual behavior
   - Steps to reproduce

---

## Quick Checklist

Before reporting an issue, verify:

- [ ] BladeRF detected: `lsusb | grep Nuand` shows device
- [ ] Permissions OK: `bladeRF-cli -p` works without sudo
- [ ] Dependencies installed: `pip3 install -r requirements.txt`
- [ ] Server starts: `python3 backend/main.py` shows no errors
- [ ] Browser console: No red errors (F12)
- [ ] Firewall open: `sudo ufw allow 5000` if accessing remotely
- [ ] Gain sufficient: Try 50-60 dB if no signals visible
- [ ] Antenna connected: Check physical connections

---

**Version**: 2.0.0
**Last Updated**: 2026-02-10
