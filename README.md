# Spectrum Analyzer for BladeRF

Web-based real-time spectrum analyzer with waterfall display for BladeRF 2.0 SDR on Raspberry Pi 5 (DragonOS).

## Features

- **Real-time spectrum display** with zoom, pan, and auto-scaling
- **WebGL-accelerated waterfall** with multiple colormaps (viridis, plasma, inferno, turbo, grayscale)
- **Interactive markers** - normal, delta, and peak search
- **Peak hold trace** with configurable decay
- **Software AGC** - automatic gain control with hysteresis
- **Advanced DSP** - overlap-save FFT, multiple window functions, DC removal, peak-preserving downsampling
- **Wide frequency coverage**: 47 MHz - 6 GHz
- **Tunable bandwidth**: 1 - 61.44 MHz
- **Binary WebSocket protocol** for low-latency data transfer
- **Keyboard shortcuts** for frequency tuning and analysis
- **Remote access**: Access from any device on your network

## Requirements

### Hardware
- Raspberry Pi 5 (or compatible ARM64 system)
- BladeRF 2.0 micro SDR
- DragonOS (or similar Linux distribution)

### Software
All dependencies are listed in [requirements.txt](requirements.txt):
- Python 3.11+
- FastAPI + uvicorn (async web framework)
- NumPy, SciPy
- pyFFTW (FFTW3 Python wrapper)
- GNU Radio 3.10+ with gr-osmosdr

## Installation

### Quick Install

```bash
cd /home/dragon/Repos/Spectrum_Analyzer
pip3 install -r requirements.txt
```

### Verify Installation

Check that BladeRF is detected:

```bash
bladeRF-cli -p
```

You should see your BladeRF device information.

## Usage

### Start the Application

```bash
python3 backend/main.py
```

With options:

```bash
python3 backend/main.py --debug                    # Debug logging
python3 backend/main.py --port 8080                # Custom port
python3 backend/main.py --sample-rate 5e6           # 5 MS/s
python3 backend/main.py --fft-size 4096             # Higher resolution
```

### Access the Web Interface

Open a web browser and navigate to:
- **Local access**: http://localhost:5000
- **Network access**: http://[raspberry-pi-ip]:5000

### Controls

#### Starting/Stopping
- Click **Start** to begin streaming
- Click **Stop** to stop streaming

#### Frequency Tuning
- **Manual entry**: Enter frequency in MHz (47 - 6000 MHz)
- **Preset buttons**: Quick access to common frequencies
  - FM Radio (100 MHz)
  - ISM Band (433.92 MHz)
  - ISM Band (915 MHz)
  - WiFi (2.4 GHz)

#### DSP Settings
- **Window function**: Hanning, Blackman-Harris (default), Blackman, Flat-top, Kaiser, Rectangular
- **Averaging**: None, linear, or exponential with adjustable alpha
- **DC removal**: IIR high-pass filter to remove DC offset
- **Peak hold**: Track maximum signal levels over time

#### Display Settings
- **Colormap**: Viridis, Plasma, Inferno, Turbo, Grayscale
- **Auto-scale**: Automatic dB range adjustment
- **AGC**: Software automatic gain control

#### Keyboard Shortcuts
| Key | Action |
|-----|--------|
| `M` | Add marker at peak |
| `N` | Next peak search |
| `D` | Add delta marker |
| `C` | Clear all markers |
| `H` | Toggle peak hold |
| `R` | Reset zoom |
| `A` | Toggle auto-scale |
| `+`/`-` | Adjust dB range |

#### Mouse Controls
- **Scroll wheel**: Zoom in/out (centered on cursor)
- **Click + drag**: Pan across spectrum
- **Double-click**: Reset zoom to full span

## Architecture

### Backend (Python/FastAPI)
```
backend/
├── main.py                     # Entry point: argparse + uvicorn
├── app.py                      # FastAPI factory with async lifespan
├── config.py                   # Dataclass-based configuration
├── logging_config.py           # Centralized logging with file rotation
├── api/
│   ├── routes.py               # REST: /api/status, /api/check_device, /api/reconnect
│   └── websocket.py            # Native WebSocket: /ws (binary data out, text commands in)
├── hardware/
│   ├── bladerf_interface.py    # BladeRF control via gr-osmosdr (dedicated thread)
│   └── probe.py                # Device probing
├── dsp/
│   ├── pipeline.py             # FFT pipeline: window, FFT, power spectrum, averaging
│   ├── windows.py              # Window functions with correction factors
│   ├── dc_removal.py           # IIR high-pass DC removal
│   ├── downsampler.py          # Peak-preserving decimation
│   └── agc.py                  # Software automatic gain control
└── streaming/
    ├── manager.py              # StreamManager: coordinates 3 threads + queues
    └── protocol.py             # Binary packet encoder (v2 protocol)
```

### Frontend (ES6 Modules)
```
static/
├── index.html                  # Main page (single <script type="module">)
├── css/style.css               # Styling
└── js/
    ├── main.js                 # Entry point: init, render loop, state wiring
    ├── modules/
    │   ├── connection.js       # Native WebSocket with auto-reconnect
    │   ├── protocol.js         # Binary packet parser (DataView-based)
    │   ├── state.js            # Reactive state store with change listeners
    │   ├── controls.js         # UI control bindings
    │   └── keyboard.js         # Keyboard shortcuts
    ├── rendering/
    │   ├── spectrum-renderer.js  # Canvas 2D spectrum with zoom support
    │   ├── waterfall-renderer.js # WebGL waterfall with ring buffer
    │   ├── grid-overlay.js       # Canvas overlay: grid, labels, markers
    │   ├── zoom-controller.js    # Mouse wheel zoom, drag pan
    │   └── colormap.js           # Colormap generation (viridis, plasma, etc.)
    └── analysis/
        └── markers.js          # Normal/delta markers, peak search
```

### Threading Model
```
[GNU Radio Thread]          [DSP Thread]              [asyncio Main Thread]
  BladeRF osmosdr             FFT + windowing           FastAPI + WebSocket
  DataSink block              DC removal, averaging     HTTP routes, broadcast
       |                           |                          |
       +--- threading.Queue -------+--- loop.call_soon -------+
            (native threads)        threadsafe()
                                    (asyncio.Queue)
```

This design avoids the eventlet monkey-patching issue that caused deadlocks with GNU Radio's native C++ pthreads.

## Performance

### Typical Performance on Raspberry Pi 5
- **Update Rate**: 30-60 FPS
- **CPU Usage**: <50%
- **Memory**: ~200 MB
- **Latency**: <100ms from RF to display

### Configuration Tips
- Use `--fft-size 1024` for higher update rates at lower resolution
- Use `--fft-size 4096` for higher frequency resolution
- Use `--sample-rate 1e6` for lower CPU usage
- Blackman-Harris window (default) gives -92 dB sidelobes

## Troubleshooting

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for detailed guidance.

### Quick Checks
```bash
# Check USB connection
lsusb | grep Nuand

# Verify device
bladeRF-cli -p

# Check firewall
sudo ufw allow 5000
```

## Logging

See [LOGGING.md](LOGGING.md) for detailed logging configuration.

Log files are written to `logs/`:
```
logs/
├── app.log           # Main application log (INFO+)
├── error.log         # Errors only (ERROR+)
├── debug.log         # Full debug output (DEBUG+)
├── hardware/
│   └── bladerf.log   # BladeRF hardware operations
└── streaming/
    └── stream.log    # Streaming and processing
```

## License

MIT License - see LICENSE file for details

## Credits

- Built for DragonOS on Raspberry Pi 5
- Uses BladeRF SDR from Nuand
- Powered by GNU Radio and gr-osmosdr
- FFT processing with FFTW3 via pyFFTW

## Support

For issues and questions:
- Check [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
- Review BladeRF documentation: https://www.nuand.com
- GNU Radio resources: https://www.gnuradio.org

---

**Version**: 2.0.0
**Last Updated**: 2026-02-10
