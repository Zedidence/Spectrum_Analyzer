# Changelog

## Version 2.0.0 - 2026-02-10

### Complete Architecture Rebuild

v2.0 is a ground-up rewrite addressing the fundamental architectural flaw in v1: **eventlet monkey-patches Python's threading primitives, but GNU Radio uses native C++ pthreads**, causing deadlocks under load, silent data drops, and race conditions.

### Architecture Changes

| Component | v1 | v2 |
|-----------|-----|-----|
| Web framework | Flask + eventlet | FastAPI + uvicorn (native asyncio) |
| WebSocket | Socket.IO (JSON) | Native WebSocket (binary frames) |
| Threading | Eventlet greenlets + real threads (conflict) | 3 isolated threads with queue bridges |
| DSP | Hanning-only, no overlap, mean decimation | Multi-window, overlap-save, peak-preserving |
| Frontend modules | IIFE globals, load-order dependent | ES6 modules with explicit imports |
| Spectrum renderer | Canvas 2D (basic) | Canvas 2D with zoom/pan/markers |
| Waterfall renderer | WebGL ring buffer | WebGL ring buffer + multiple colormaps |
| State management | Global object | Reactive store with change listeners |

### New Features

#### Backend
- **FastAPI + uvicorn**: No monkey-patching, proper asyncio integration
- **3-thread architecture**: GNU Radio thread, DSP thread, asyncio main thread connected by queues
- **Binary WebSocket protocol v2**: 8-byte frame header + 56-byte spectrum header + Float32 data
- **Overlap-save FFT**: 50% overlap for better spectral estimation
- **Multiple window functions**: Hanning, Blackman-Harris (default, -92 dB sidelobes), Blackman, Flat-top, Kaiser (6/10/14), Rectangular
- **DC removal**: IIR high-pass filter via scipy.signal.lfilter
- **Peak-preserving downsampling**: np.max() per bin group (signals don't disappear)
- **Peak hold trace**: Element-wise maximum tracking across frames
- **Software AGC**: Target -20 dBFS, 6 dB hysteresis, 3 dB gain steps, 1s rate limiting
- **Proper dBFS normalization**: Corrected for window gain and FFT size
- **Centralized logging**: Rotating file handlers with component-specific log files
- **Dataclass configuration**: Type-safe config with validation

#### Frontend
- **ES6 modules**: Clean dependency graph, no global state pollution
- **Native WebSocket**: Auto-reconnect, binary frame parsing
- **Reactive state store**: `.on(key, callback)` change notification
- **Zoom and pan**: Mouse wheel zoom centered on cursor, click-drag pan, double-click reset
- **Marker system**: Normal markers, delta markers, peak search with exclusion zones
- **Grid overlay**: Separate canvas layer with frequency/dB labels that adapt to zoom level
- **Auto-scale dB**: Smooth exponential approach to optimal range, snaps to 10 dB grid
- **Multiple colormaps**: Viridis, Plasma, Inferno, Turbo, Grayscale (hot-swappable via WebGL texture)
- **Keyboard shortcuts**: M (marker), N (next peak), D (delta), C (clear), H (peak hold), R (reset zoom), A (auto-scale), +/- (dB range)
- **DSP controls**: Window type, averaging mode/alpha, DC removal, peak hold toggle

### Files Removed (v1)
- `backend/signal_processor.py` - replaced by `dsp/pipeline.py`
- `backend/bladerf_interface.py` (root) - replaced by `hardware/bladerf_interface.py`
- `backend/processing.py` - replaced by `streaming/manager.py`
- `backend/state.py` - replaced by FastAPI `app.state`
- `backend/routes.py` - replaced by `api/routes.py`
- `backend/socketio_handlers.py` - replaced by `api/websocket.py`
- `static/js/app.js` - replaced by `main.js`
- `static/js/spectrum.js` - replaced by `rendering/spectrum-renderer.js`
- `static/js/waterfall.js` - replaced by `rendering/waterfall-renderer.js`
- `static/js/waterfall-webgl.js` - replaced by `rendering/waterfall-renderer.js`
- `static/js/socket-handler.js` - replaced by `modules/connection.js`
- `static/js/state.js` - replaced by `modules/state.js`
- `static/js/ui-controller.js` - replaced by `modules/controls.js`

### Breaking Changes
- Flask + eventlet backend completely replaced by FastAPI + uvicorn
- Socket.IO replaced by native WebSocket (binary protocol)
- All frontend JavaScript rewritten as ES6 modules
- Entry point changed from `backend/app.py` to `backend/main.py`
- requirements.txt updated: flask/eventlet removed, fastapi/uvicorn added

### Migration
This is a full rewrite. No incremental migration path from v1 - replace all files.

```bash
pip3 install -r requirements.txt
python3 backend/main.py
```

---

## Version 1.0.3 - 2026-02-04

### New Features
- GUI controls for sample rate (0.5 - 10 MS/s) and FFT size (256 - 8192)
- Settings adjustable from web interface without editing code

---

## Version 1.0.2 - 2026-02-04

### Performance Optimizations
- Removed artificial 50ms processing rate limit (reduced to 1ms)
- Processing loop now drains queue as fast as data arrives

---

## Version 1.0.1 - 2026-02-04

### Critical Bug Fixes
- Fixed no visual display: replaced `blocks.vector_sink_c` with custom `DataSink` GNU Radio block
- Fixed WebSocket connection stability with better reconnection handling
- Added comprehensive logging system throughout the stack
- Added TROUBLESHOOTING.md and LOGGING.md documentation
