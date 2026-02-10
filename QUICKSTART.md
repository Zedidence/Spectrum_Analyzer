# Quick Start Guide

## 1. Install Dependencies

```bash
cd /home/dragon/Repos/Spectrum_Analyzer
pip3 install -r requirements.txt
```

## 2. Verify BladeRF Connection

```bash
bladeRF-cli -p
```

You should see your BladeRF device information.

## 3. Start the Spectrum Analyzer

```bash
python3 backend/main.py
```

You should see output like:
```
Starting Spectrum Analyzer v2.0
  FastAPI + uvicorn (no eventlet)
  FFT size: 2048
  Sample rate: 2.00 MS/s
  Target FPS: 60
Application initialized, ready for connections
INFO:     Uvicorn running on http://0.0.0.0:5000
```

## 4. Open Web Browser

On the Raspberry Pi or any device on the same network:

- **Local (on Pi)**: http://localhost:5000
- **Remote (from network)**: http://[pi-ip-address]:5000

## 5. Start Analyzing

1. Click **Start** to begin streaming
2. Wait a moment for the BladeRF to initialize
3. You should see:
   - Real-time spectrum display (top) with grid overlay
   - Waterfall display (bottom) with color-mapped history

## 6. Tune to a Signal

### Try FM Radio (88-108 MHz)
1. Click the **FM (100 MHz)** preset button
2. You should see FM radio stations as peaks in the spectrum

### Try WiFi (2.4 GHz)
1. Click the **WiFi (2.4 GHz)** preset button
2. You should see WiFi activity

### Try ISM Band (433.92 MHz)
1. Click the **ISM (433.92 MHz)** preset button
2. Look for wireless sensor signals, remote controls, etc.

## 7. Adjust Settings

- **Gain**: Increase if signals are too weak, decrease if saturated
- **Bandwidth**: Wider bandwidth = more spectrum visible
- **Window function**: Blackman-Harris (default) for best sidelobe suppression
- **Averaging**: Exponential for smooth display, None for fastest response
- **Colormap**: Choose from Viridis, Plasma, Inferno, Turbo, Grayscale

## 8. Interactive Features

### Zoom and Pan
- **Scroll wheel**: Zoom in/out (centered on cursor)
- **Click + drag**: Pan across spectrum
- **Double-click**: Reset to full span

### Markers
- **M**: Place marker at current peak
- **N**: Find next peak
- **D**: Add delta marker (shows difference from reference)
- **C**: Clear all markers

### Other Shortcuts
- **H**: Toggle peak hold trace
- **A**: Toggle auto-scale dB range
- **R**: Reset zoom
- **+/-**: Manually adjust dB range

## Troubleshooting

### "Failed to initialize hardware"
- Check BladeRF USB connection
- Run `bladeRF-cli -p` to verify device

### Can't access web interface
- Check firewall: `sudo ufw allow 5000`
- Verify server is running: `ps aux | grep main.py`

### No signals visible
- Increase gain (try 40-50 dB)
- Check antenna is connected
- Verify frequency is correct

### Low frame rate
- Try `python3 backend/main.py --fft-size 1024`
- Close other CPU-intensive applications

---

For more details, see [README.md](README.md)
