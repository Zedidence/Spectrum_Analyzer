# Logging Configuration Guide

## Overview

The spectrum analyzer has comprehensive logging throughout the codebase for troubleshooting. By default, it runs at **INFO** level to reduce terminal spam while still showing important events.

## Log Levels

### INFO (Default)
- Shows important events (startup, connections, errors, periodic stats)
- Minimal terminal output
- Recommended for normal operation

### DEBUG (Troubleshooting)
- Shows detailed operation of every component
- Verbose output with function calls and data flow
- Use when diagnosing problems

### WARNING/ERROR
- Only shows warnings and errors
- Very quiet operation
- Not recommended as you'll miss important status updates

## Changing Log Level

### Method 1: Edit Source Files (Persistent)

**Backend Files:**

In `backend/app.py` line 23:
```python
logging.basicConfig(
    level=logging.INFO,  # Change to logging.DEBUG for verbose output
    format='%(asctime)s - %(name)s - %(levelname)s - [%(funcName)s:%(lineno)d] %(message)s'
)
```

In `backend/bladerf_interface.py` line 20:
```python
logging.basicConfig(
    level=logging.INFO,  # Change to logging.DEBUG for verbose output
    format='%(asctime)s - %(name)s - %(levelname)s - [%(funcName)s] %(message)s'
)
```

### Method 2: Environment Variable (Temporary)

Set before running:
```bash
export PYTHONVERBOSE=1
export LOGLEVEL=DEBUG
python3 backend/app.py
```

## Understanding Log Messages

### INFO Level Examples

```
✓ Hardware initialized successfully
✓ BladeRF setup complete - ready to stream
✓ Flowgraph running - data should be flowing
✓ First IQ data received - processing pipeline active
📊 Stats: Update rate = 18.2 Hz, Timeouts = 0, Errors = 0
```

### DEBUG Level Examples (More Verbose)

```
DEBUG - [setup_device] Creating GNU Radio top_block
DEBUG - [setup_device] Creating osmosdr source for BladeRF
DEBUG - [setup_device] Setting sample rate: 2.40 MS/s
DEBUG - [work] DataSink: processed 204800 samples, queue size: 15, drops: 0
DEBUG - [get_iq_data] Got IQ data: shape=(2048,), mean_power=1.23e-04
```

## Common Log Messages

### Normal Operation

| Message | Meaning |
|---------|---------|
| `✓ Streaming started successfully` | BladeRF streaming active |
| `✓ First IQ data received` | Data flowing through pipeline |
| `📊 Stats: Update rate = X Hz` | Current FFT processing rate |
| `✓ Frequency: X MHz → Y MHz` | Frequency changed successfully |

### Warnings (Need Attention)

| Message | Meaning | Action |
|---------|---------|--------|
| `⚠ Queue full - dropped N chunks` | Processing too slow | Reduce averaging, bandwidth, or FFT size |
| `⚠ Data timeout - no IQ samples` | BladeRF not sending data | Check USB connection |
| `⚠ Queue is empty` | No data in queue | BladeRF connection problem |

### Errors (Require Action)

| Message | Meaning | Action |
|---------|---------|--------|
| `✗ Failed to setup BladeRF` | Cannot initialize device | Check `bladeRF-cli -p` |
| `✗ Connection error` | WebSocket failed | Check firewall, port 5000 |
| `✗ Error in streaming thread` | Flowgraph crashed | Check logs for details |

## Queue Full Messages

### Why It Happens

The "Queue full - dropped N chunks" warning appears when:
1. Data arrives from BladeRF faster than it can be processed
2. FFT computation takes too long
3. Network transmission is slow
4. CPU is overloaded

### Solutions

#### 1. Reduce Averaging (Fastest Fix)

In `backend/app.py` line 64:
```python
averaging = 1  # Reduced from 2 (no averaging, fastest)
```

#### 2. Reduce FFT Size

In `backend/app.py` line 63:
```python
fft_size = 1024  # Reduced from 2048 (lower resolution, faster)
```

#### 3. Reduce Sample Rate

In `backend/app.py` line 62:
```python
sample_rate = 1e6  # 1 MS/s instead of 2.4 MS/s
```

#### 4. Increase Queue Size

In `backend/bladerf_interface.py` line 109:
```python
self.data_queue = queue.Queue(maxsize=50)  # Increased from 20
```

### Rate-Limited Logging

The queue full message is **rate-limited** to once every 5 seconds with a count of dropped chunks. This prevents terminal spam while still alerting you to the issue.

Before rate limiting:
```
DEBUG - [work] DataSink: queue full, dropping data
DEBUG - [work] DataSink: queue full, dropping data
DEBUG - [work] DataSink: queue full, dropping data
... (thousands of lines)
```

After rate limiting:
```
⚠ Queue full - dropped 243 chunks (processing too slow)
... (5 seconds later)
⚠ Queue full - dropped 189 chunks (processing too slow)
```

## Performance Monitoring

### Check Processing Rate

Look for this message every 10 seconds:
```
📊 Stats: Update rate = 18.2 Hz, Timeouts = 0, Errors = 0
```

**Good rates:** 15-25 Hz
**Slow rates:** <10 Hz (indicates processing bottleneck)
**Excessive rates:** >30 Hz (unnecessary CPU usage)

### Check Queue Status

With DEBUG logging enabled, you'll see:
```
DataSink: processed 204800 samples, queue size: 15, drops: 0
```

**Healthy queue:** 5-15 items
**Filling up:** 15-20 items (close to maxsize=20)
**Overflow:** Drops > 0 (processing too slow)

## Frontend Logging (Browser Console)

Frontend logs are always available in browser console (F12).

### Normal Operation
```
✓ WebSocket connected successfully
✓ First FFT data packet received!
✓ SpectrumDisplay: First data received
✓ WaterfallDisplay: First line added
📈 Display update rate: 15.1 Hz
```

### Reducing Frontend Verbosity

Edit `static/js/app.js`:

Comment out periodic logging:
```javascript
// Line 146-148: Reduce packet count logging frequency
if (dataReceivedCount % 500 === 0) {  // Changed from 100
    console.log(`📊 Received ${dataReceivedCount} FFT packets`);
}

// Line 204-211: Comment out detailed FFT processing logs
/*
if (dataReceivedCount % 100 === 0) {
    console.log(`Processing FFT data:...`);
}
*/
```

## Recommended Settings

### Normal Operation (Default)
```python
# backend/app.py
logging.basicConfig(level=logging.INFO)
averaging = 2
fft_size = 2048
sample_rate = 2.4e6
```

### Troubleshooting Mode
```python
# backend/app.py
logging.basicConfig(level=logging.DEBUG)
averaging = 2
fft_size = 2048
sample_rate = 2.4e6
```

### Low-Resource Mode (Raspberry Pi under load)
```python
# backend/app.py
logging.basicConfig(level=logging.INFO)
averaging = 1  # No averaging
fft_size = 1024  # Smaller FFT
sample_rate = 1e6  # 1 MS/s
```

### High-Performance Mode (Powerful system)
```python
# backend/app.py
logging.basicConfig(level=logging.INFO)
averaging = 4  # More smoothing
fft_size = 4096  # Higher resolution
sample_rate = 5e6  # 5 MS/s
```

## Log File Output

### Save Logs to File

```bash
# Redirect both stdout and stderr to file
python3 backend/app.py 2>&1 | tee spectrum_analyzer.log

# View log file in real-time
tail -f spectrum_analyzer.log

# Search log file for errors
grep -i "error" spectrum_analyzer.log
```

### Rotate Log Files

```bash
# Keep last 5 logs
python3 backend/app.py 2>&1 | tee -a logs/app_$(date +%Y%m%d_%H%M%S).log

# Clean old logs
find logs/ -name "app_*.log" -mtime +7 -delete
```

## Summary

- **Default (INFO):** Clean logs, shows important events only
- **Troubleshooting (DEBUG):** Verbose logs for diagnosis
- **Queue full warning:** Rate-limited to every 5 seconds
- **Adjust averaging/FFT size:** If queue is overflowing
- **Browser console:** Always available for frontend debugging

---

**Last Updated:** 2026-02-04
**Version:** 1.0.2
