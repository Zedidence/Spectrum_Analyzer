# Logging Configuration Guide

## Overview

The spectrum analyzer v2.0 uses a centralized logging system with rotating file handlers and component-specific log files. Logging is configured in `backend/logging_config.py`.

## Log Directory Structure

```
logs/
├── app.log           # Main application log (INFO+)
├── error.log         # Errors only (ERROR+)
├── debug.log         # Full debug output (DEBUG+)
├── hardware/
│   └── bladerf.log   # BladeRF hardware + DSP operations
└── streaming/
    └── stream.log    # Streaming, protocol, and WebSocket operations
```

Each log file uses rotating file handlers:
- **Max size**: 10 MB per file
- **Backups**: 5 rotated files kept

## Log Levels

### INFO (Default)
- Important events: startup, connections, errors, periodic stats
- Minimal terminal output
- Recommended for normal operation

### DEBUG (Troubleshooting)
- Detailed operation of every component
- FFT processing times, queue sizes, frame encoding
- Use when diagnosing problems

### WARNING/ERROR
- Only warnings and errors
- Very quiet operation

## Changing Log Level

### Command Line (Recommended)

```bash
# Normal operation (INFO)
python3 backend/main.py

# Debug mode
python3 backend/main.py --debug
```

### Environment Variable

```bash
LOGLEVEL=DEBUG python3 backend/main.py
```

### Programmatic

The logging level can be changed at runtime:

```python
from logging_config import set_log_level
import logging
set_log_level(logging.DEBUG)
```

## Component Loggers

Each backend module gets its own logger via `logging.getLogger(__name__)`:

| Logger Name | Log File | Description |
|-------------|----------|-------------|
| `hardware.bladerf_interface` | `hardware/bladerf.log` | BladeRF device control |
| `hardware.probe` | `hardware/bladerf.log` | Device probing |
| `dsp.pipeline` | `hardware/bladerf.log` | FFT processing pipeline |
| `dsp.dc_removal` | `hardware/bladerf.log` | DC removal filter |
| `dsp.agc` | `hardware/bladerf.log` | Automatic gain control |
| `streaming.manager` | `streaming/stream.log` | Stream thread coordination |
| `streaming.protocol` | `streaming/stream.log` | Binary packet encoding |
| `api.websocket` | `streaming/stream.log` | WebSocket endpoint |
| `api.routes` | `streaming/stream.log` | REST API routes |

Third-party loggers (uvicorn, websockets) are set to WARNING to reduce noise.

## Understanding Log Messages

### Startup Sequence
```
======================================================================
Logging initialized
  Log directory: /home/dragon/Repos/Spectrum_Analyzer/logs
  Console level: INFO
  File level: DEBUG
======================================================================
Starting Spectrum Analyzer v2.0
  FastAPI + uvicorn (no eventlet)
  FFT size: 2048
  Sample rate: 2.00 MS/s
  Target FPS: 60
======================================================================
Application initialized, ready for connections
```

### Normal Operation
```
INFO - WebSocket client connected
INFO - Starting stream: 100.0 MHz, 2.0 MS/s, gain 40.0 dB
INFO - GNU Radio flowgraph started
INFO - DSP thread started
INFO - Broadcast loop started
```

### Warnings
| Message | Meaning | Action |
|---------|---------|--------|
| `IQ queue full, dropping data` | DSP thread can't keep up | Reduce FFT size or sample rate |
| `WebSocket send failed` | Client disconnected during send | Normal if client closed tab |

### Errors
| Message | Meaning | Action |
|---------|---------|--------|
| `Failed to initialize BladeRF` | Device not found or busy | Check `bladeRF-cli -p` |
| `DSP thread error` | Exception in FFT processing | Check debug.log for traceback |
| `GNU Radio flowgraph error` | Flowgraph failed to start | Check USB connection |

## Performance Monitoring

### DSP Thread Stats

With debug logging, the DSP thread reports processing times:
```
DEBUG - FFT processed in 2.3ms, queue depth: 5
```

### Queue Health

- **IQ queue**: 256 slots (~128ms buffer at 2 MS/s)
- **Result queue**: 8 slots (small, always want latest)
- Healthy: queue depth stays low (<50% capacity)
- Overloaded: queue full warnings appear

## Log File Management

### View Logs in Real-Time

```bash
# Main application log
tail -f logs/app.log

# Hardware operations
tail -f logs/hardware/bladerf.log

# Streaming/WebSocket
tail -f logs/streaming/stream.log

# Errors only
tail -f logs/error.log
```

### Clear Logs

```python
from logging_config import clear_logs
clear_logs()
```

Or manually:
```bash
rm -f logs/*.log logs/hardware/*.log logs/streaming/*.log
```

### Check Log Sizes

```python
from logging_config import get_log_files
for name, info in get_log_files().items():
    print(f"{name}: {info['size_human']}")
```

## Frontend Logging

Frontend logs are available in the browser console (F12):

```
[Connection] WebSocket connected
[Protocol] Frame: type=1, flags=0x0001, payload=8256 bytes
[Spectrum] Rendering 2048 bins, zoom: 0.00-1.00
```

Filter by module name in the browser console to focus on specific components.

## Recommended Settings

### Normal Operation
```bash
python3 backend/main.py
# INFO console, DEBUG to files, 2 MS/s, 2048 FFT
```

### Troubleshooting
```bash
python3 backend/main.py --debug
# DEBUG console + files, full verbosity
```

### Low-Resource Mode
```bash
python3 backend/main.py --fft-size 1024 --sample-rate 1e6
# Reduced processing load for constrained systems
```

### High-Resolution Mode
```bash
python3 backend/main.py --fft-size 4096 --sample-rate 5e6
# Higher resolution, requires more CPU
```

---

**Version**: 2.0.0
**Last Updated**: 2026-02-10
