# Quick Start Guide

## 1. Verify BladeRF Connection

```bash
bladeRF-cli -i
```

You should see your BladeRF device information. Type `quit` to exit.

## 2. Start the Spectrum Analyzer

```bash
cd /home/dragon/Repos/Spectrum_Analyzer
./run.sh
```

You should see output like:
```
Starting Spectrum Analyzer...
Access the web interface at: http://192.168.x.x:5000
Or locally at: http://localhost:5000

2026-02-04 12:00:00 - __main__ - INFO - Hardware initialized successfully
2026-02-04 12:00:00 - __main__ - INFO - Starting Flask server on http://0.0.0.0:5000
```

## 3. Open Web Browser

On the Raspberry Pi or any device on the same network, open a web browser and navigate to:

- **Local (on Pi)**: http://localhost:5000
- **Remote (from network)**: http://[pi-ip-address]:5000

Example: `http://192.168.1.100:5000`

## 4. Start Analyzing

1. Click the **▶ Start** button
2. Wait a moment for the BladeRF to initialize
3. You should see:
   - Real-time spectrum display (top)
   - Waterfall display (bottom)
   - Update rate showing ~10-15 Hz

## 5. Tune to a Signal

### Try FM Radio (88-108 MHz)
1. Click the **FM (100 MHz)** preset button
2. You should see FM radio stations as peaks in the spectrum

### Try WiFi (2.4 GHz)
1. Click the **WiFi (2.4 GHz)** preset button
2. Set bandwidth to 5 MHz
3. You should see WiFi activity

### Try ISM Band (433.92 MHz)
1. Click the **ISM (433.92 MHz)** preset button
2. Look for wireless sensor signals, remote controls, etc.

## 6. Adjust Settings

- **Gain**: Increase if signals are too weak, decrease if saturated
- **Bandwidth**: Smaller bandwidth = better frequency resolution
- **Frequency**: Use arrow keys for fine tuning
  - ↑/↓: ±1 MHz
  - ←/→: ±0.1 MHz

## Troubleshooting

### "Failed to initialize hardware"
- Check BladeRF USB connection
- Run `bladeRF-cli -p` to verify device

### Can't access web interface
- Check firewall: `sudo ufw allow 5000`
- Verify Flask server is running: `ps aux | grep app.py`

### Low frame rate
- Close other applications
- Reduce bandwidth to 1-2 MHz
- Lower gain setting

### No signals visible
- Increase gain (try 40-50 dB)
- Check antenna is connected
- Verify frequency is correct

## Next Steps

- Explore different frequency ranges
- Fine-tune gain for optimal signal-to-noise ratio
- Try monitoring different wireless protocols
- Access remotely from phone or tablet

## Keyboard Shortcuts

- `Space`: Start/Stop streaming
- `↑`/`↓`: Frequency ±1 MHz
- `←`/`→`: Frequency ±0.1 MHz

---

For more details, see [README.md](README.md)
