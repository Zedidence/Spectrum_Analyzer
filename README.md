# Spectrum Analyzer for BladeRF

Web-based real-time spectrum analyzer with waterfall display for BladeRF SDR on Raspberry Pi 5 (DragonOS).

![Spectrum Analyzer](docs/screenshots/main.png)

## Features

- **Real-time spectrum display** with GPU-accelerated Canvas rendering
- **Scrolling waterfall display** with 500-line history
- **Wide frequency coverage**: 20 MHz - 6 GHz
- **Tunable bandwidth**: 200 kHz - 5 MHz
- **Remote access**: Access from any device on your network
- **Keyboard shortcuts** for quick frequency tuning
- **ARM NEON optimized** FFT processing using FFTW3
- **Responsive design**: Works on desktop, tablet, and mobile

## Requirements

### Hardware
- Raspberry Pi 5 (or compatible ARM64 system)
- BladeRF 2.0 micro SDR
- DragonOS (or similar Linux distribution)

### Software
All dependencies are listed in [requirements.txt](requirements.txt):
- Python 3.13+
- Flask 3.0+
- Flask-SocketIO 5.3+
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
bladeRF-cli -i
```

You should see your BladeRF device information.

## Usage

### Start the Application

```bash
./run.sh
```

Or directly:

```bash
python3 backend/app.py
```

### Access the Web Interface

Open a web browser and navigate to:
- **Local access**: http://localhost:5000
- **Network access**: http://[raspberry-pi-ip]:5000

For example: `http://192.168.1.100:5000`

### Controls

#### Starting/Stopping
- Click **▶ Start** to begin streaming
- Click **⏹ Stop** to stop streaming

#### Frequency Tuning
- **Manual entry**: Enter frequency in MHz (20 - 6000 MHz)
- **Preset buttons**: Quick access to common frequencies
  - FM Radio (100 MHz)
  - ISM Band (433.92 MHz)
  - ISM Band (915 MHz)
  - WiFi (2.4 GHz)
- **Keyboard shortcuts**:
  - `↑` / `↓`: Adjust frequency by ±1 MHz
  - `←` / `→`: Adjust frequency by ±0.1 MHz
  - `Space`: Toggle streaming on/off

#### Other Controls
- **Bandwidth**: Select from 200 kHz to 5 MHz
- **Gain**: Adjust RX gain from 0 to 60 dB using slider

## Architecture

### Backend (Python/Flask)
```
backend/
├── app.py                  # Flask server with WebSocket
├── bladerf_interface.py    # BladeRF control via gr-osmosdr
└── signal_processor.py     # FFT and power spectrum calculation
```

### Frontend (HTML/JavaScript)
```
static/
├── index.html              # Main web page
├── css/style.css           # Styling
└── js/
    ├── app.js              # WebSocket client and control logic
    ├── spectrum.js         # Spectrum display (Canvas 2D)
    └── waterfall.js        # Waterfall display (Canvas 2D)
```

## Performance

### Typical Performance on Raspberry Pi 5
- **FFT Update Rate**: 10-20 Hz
- **CPU Usage**: 30-40% (single core)
- **Memory**: ~200 MB
- **Latency**: <200ms from RF to display

### Optimization Tips
- Use smaller FFT sizes (1024-2048) for higher update rates
- Reduce bandwidth for lower CPU usage
- Lower gain to reduce signal processing load
- Close other applications to free resources

## Troubleshooting

### BladeRF Not Detected
```bash
# Check USB connection
lsusb | grep Nuand

# Verify device with bladeRF-cli
bladeRF-cli -p

# Check udev rules
ls /usr/lib/udev/rules.d/ | grep bladerf
```

### WebSocket Connection Issues
- Ensure Flask server is running
- Check firewall rules: `sudo ufw allow 5000`
- Verify network connectivity

### Low Frame Rate
- Reduce FFT size in [backend/app.py](backend/app.py#L35)
- Lower bandwidth setting
- Reduce averaging factor in signal processor

## Development

### Project Structure
```
Spectrum_Analyzer/
├── backend/            # Python backend
├── static/             # Web frontend
│   ├── css/
│   ├── js/
│   └── img/
├── config/             # Configuration files
├── tests/              # Unit tests
├── docs/               # Documentation
├── requirements.txt    # Python dependencies
├── run.sh              # Launch script
└── README.md           # This file
```

### Running Tests
```bash
python3 -m pytest tests/
```

### Adding Features
1. Backend changes: Modify files in [backend/](backend/)
2. Frontend changes: Modify files in [static/](static/)
3. No compilation needed - changes take effect immediately

## API Documentation

### WebSocket Events

**Client → Server**:
- `start_streaming` - Start FFT data stream
- `stop_streaming` - Stop data stream
- `set_frequency` - Set center frequency (Hz)
- `set_gain` - Set RX gain (dB)
- `set_bandwidth` - Set bandwidth (Hz)
- `get_status` - Request device status

**Server → Client**:
- `fft_data` - FFT spectrum data (array of dB values)
- `status_update` - Device status update
- `connected` - Connection confirmation
- `error` - Error message

### REST API

- `GET /api/status` - Get current device status

## License

MIT License - see LICENSE file for details

## Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Submit a pull request

## Credits

- Built for DragonOS on Raspberry Pi 5
- Uses BladeRF SDR from Nuand
- Powered by GNU Radio and gr-osmosdr
- FFT processing with FFTW3 (ARM NEON optimized)

## Support

For issues and questions:
- Check [troubleshooting](#troubleshooting) section
- Review BladeRF documentation: https://www.nuand.com
- GNU Radio resources: https://www.gnuradio.org

---

**Version**: 1.0.0
**Last Updated**: 2026-02-04
