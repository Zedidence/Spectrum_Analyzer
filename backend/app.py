#!/usr/bin/env python3
"""
Spectrum Analyzer Flask Backend
Web-based spectrum analyzer for BladeRF using Flask and WebSockets.
"""

import os
import sys
import json
import logging
import threading
import time
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit

# Add backend directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bladerf_interface import BladeRFInterface
from signal_processor import SignalProcessor

# Setup logging with detailed format
# Use INFO level for normal operation, DEBUG for troubleshooting
logging.basicConfig(
    level=logging.INFO,  # Changed from DEBUG to reduce log spam
    format='%(asctime)s - %(name)s - %(levelname)s - [%(funcName)s:%(lineno)d] %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__,
            static_folder='../static',
            static_url_path='/static')
app.config['SECRET_KEY'] = 'spectrum-analyzer-secret-key'

# Initialize SocketIO with eventlet
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Global objects
bladerf = None
processor = None
streaming_active = False
processing_thread = None


def init_hardware():
    """
    Initialize BladeRF and signal processor.

    This sets up the hardware interface and FFT processing pipeline
    with default parameters optimized for <5 MHz bandwidth.

    Returns:
        bool: True if initialization successful, False otherwise
    """
    global bladerf, processor

    try:
        logger.info("=" * 70)
        logger.info("Initializing hardware...")

        # Initialize with optimized settings for real-time performance
        sample_rate = 2.4e6  # 2.4 MS/s for <5 MHz bandwidth
        fft_size = 2048
        averaging = 1  # Reduced from 4 to speed up processing and prevent queue overflow

        logger.info(f"  Sample rate: {sample_rate/1e6:.1f} MS/s")
        logger.info(f"  FFT size: {fft_size}")
        logger.info(f"  Averaging: {averaging} FFTs (optimized for real-time)")

        # Create BladeRF interface
        logger.debug("Creating BladeRF interface...")
        bladerf = BladeRFInterface(sample_rate=sample_rate, fft_size=fft_size)

        # Create signal processor
        logger.debug("Creating signal processor...")
        processor = SignalProcessor(fft_size=fft_size, sample_rate=sample_rate, averaging=averaging)

        logger.info("✓ Hardware initialized successfully")
        logger.info("=" * 70)
        return True

    except Exception as e:
        logger.error(f"✗ Failed to initialize hardware: {e}", exc_info=True)
        return False


def processing_loop():
    """
    Background thread that processes IQ data and emits to clients.

    This is the main processing pipeline:
    1. Get IQ samples from BladeRF
    2. Compute FFT and power spectrum
    3. Apply averaging
    4. Downsample for web transmission
    5. Emit to all connected WebSocket clients

    Runs continuously until streaming_active is set to False.
    """
    global streaming_active, bladerf, processor

    logger.info("=" * 70)
    logger.info("Processing loop started")
    logger.info("=" * 70)

    update_count = 0
    error_count = 0
    timeout_count = 0
    last_stats_time = time.time()
    first_data_received = False

    while streaming_active:
        try:
            # Get IQ data from BladeRF (blocks until data available or timeout)
            iq_data = bladerf.get_iq_data(timeout=1.0)

            if iq_data is None:
                timeout_count += 1
                if timeout_count % 5 == 0:  # Log every 5 timeouts
                    logger.warning(f"⚠ Data timeout #{timeout_count} - no IQ samples received")
                    if timeout_count > 10 and not first_data_received:
                        logger.error("✗ No data received after 10 attempts - check BladeRF connection!")
                continue

            # First data received
            if not first_data_received:
                logger.info("✓ First IQ data received - processing pipeline active")
                first_data_received = True

            # Process to power spectrum (includes FFT, windowing, dB conversion)
            spectrum = processor.process_iq_samples(iq_data)

            if spectrum is None:
                # Not enough samples for averaging yet (normal during startup)
                logger.debug("Waiting for more samples to fill averaging buffer")
                continue

            # Downsample for efficient transmission (2048 -> 1024 bins)
            spectrum_downsampled = processor.downsample_spectrum(spectrum, target_bins=1024)

            # Log spectrum statistics occasionally
            if update_count % 50 == 0:
                spectrum_stats = processor.get_statistics(spectrum_downsampled)
                if spectrum_stats:
                    logger.debug(f"Spectrum: max={spectrum_stats['max_power']:.1f} dB, "
                               f"min={spectrum_stats['min_power']:.1f} dB, "
                               f"mean={spectrum_stats['mean_power']:.1f} dB")

            # Get current device status
            status = bladerf.get_status()

            # Prepare data for WebSocket transmission
            data = {
                'spectrum': spectrum_downsampled.tolist(),  # Convert numpy array to list
                'center_freq': status['center_freq'],
                'sample_rate': status['sample_rate'],
                'bandwidth': status['bandwidth'],
                'gain': status['gain'],
                'fft_size': status['fft_size'],
                'timestamp': time.time()
            }

            # Emit to all connected WebSocket clients
            socketio.emit('fft_data', data, namespace='/')

            update_count += 1
            error_count = 0  # Reset error count on success

            # Log performance statistics every 10 seconds (reduced frequency)
            elapsed = time.time() - last_stats_time
            if elapsed >= 10.0:
                update_rate = update_count / elapsed
                logger.info(f"📊 Stats: Update rate = {update_rate:.1f} Hz, "
                          f"Timeouts = {timeout_count}, Errors = {error_count}")
                update_count = 0
                timeout_count = 0
                last_stats_time = time.time()

            # Minimal rate limiting (target ~20 Hz for faster processing)
            # Reduced sleep to consume queue faster and prevent overflow
            time.sleep(0.05)  # ~50ms = 20 Hz

        except Exception as e:
            error_count += 1
            logger.error(f"✗ Error in processing loop (#{error_count}): {e}", exc_info=True)

            # If too many errors, stop streaming
            if error_count > 10:
                logger.critical("Too many errors - stopping processing loop")
                streaming_active = False
                break

            time.sleep(0.1)  # Brief pause after error

    logger.info("=" * 70)
    logger.info("✓ Processing loop stopped")
    logger.info("=" * 70)


@app.route('/')
def index():
    """Serve main page"""
    return app.send_static_file('index.html')


@app.route('/api/status', methods=['GET'])
def get_status():
    """Get current device status"""
    if bladerf:
        status = bladerf.get_status()
        status['streaming'] = streaming_active
        return jsonify(status)
    else:
        return jsonify({'error': 'Device not initialized'}), 500


@socketio.on('connect')
def handle_connect():
    """
    Handle client WebSocket connection.

    Sends initial status to newly connected client.
    """
    client_addr = request.environ.get('REMOTE_ADDR', 'unknown')
    logger.info(f"✓ Client connected: {request.sid} from {client_addr}")

    # Send current device status to client
    if bladerf:
        status = bladerf.get_status()
        status['streaming'] = streaming_active
        logger.debug(f"Sending initial status to {request.sid}: {status}")
        emit('status_update', status)
    else:
        logger.warning("BladeRF not initialized - cannot send status")

    # Send connection confirmation
    emit('connected', {'message': 'Connected to Spectrum Analyzer Backend'})
    logger.debug(f"Connection handshake complete for {request.sid}")


@socketio.on('disconnect')
def handle_disconnect():
    """
    Handle client WebSocket disconnection.
    """
    logger.info(f"✗ Client disconnected: {request.sid}")


@socketio.on('start_streaming')
def handle_start_streaming():
    """
    Start FFT data streaming.

    This starts the BladeRF hardware and the processing pipeline.
    """
    global streaming_active, processing_thread

    logger.info(f"Start streaming request from client {request.sid}")

    if streaming_active:
        logger.warning("Already streaming - ignoring request")
        emit('error', {'message': 'Already streaming'})
        return

    logger.info("=" * 70)
    logger.info("Starting streaming...")
    logger.info("=" * 70)

    # Start BladeRF streaming (initializes hardware and flowgraph)
    logger.info("Step 1: Starting BladeRF hardware")
    if not bladerf.start_streaming():
        logger.error("✗ Failed to start BladeRF")
        emit('error', {'message': 'Failed to start BladeRF - check device connection'})
        return

    logger.info("✓ BladeRF started successfully")

    # Start processing thread
    logger.info("Step 2: Starting processing thread")
    streaming_active = True
    processing_thread = threading.Thread(target=processing_loop, daemon=True)
    processing_thread.start()
    logger.info("✓ Processing thread started")

    # Notify client
    emit('status_update', {'streaming': True})
    logger.info("=" * 70)
    logger.info("✓ Streaming active - FFT data will be sent to clients")
    logger.info("=" * 70)


@socketio.on('stop_streaming')
def handle_stop_streaming():
    """
    Stop FFT data streaming.

    This stops the processing pipeline and BladeRF hardware.
    """
    global streaming_active

    logger.info(f"Stop streaming request from client {request.sid}")

    if not streaming_active:
        logger.warning("Not streaming - ignoring request")
        emit('error', {'message': 'Not streaming'})
        return

    logger.info("=" * 70)
    logger.info("Stopping streaming...")
    logger.info("=" * 70)

    # Stop processing thread
    logger.info("Step 1: Stopping processing thread")
    streaming_active = False

    # Wait for thread to finish
    if processing_thread:
        logger.debug("Waiting for processing thread to finish...")
        processing_thread.join(timeout=3.0)
        if processing_thread.is_alive():
            logger.warning("⚠ Processing thread did not finish in time")
        else:
            logger.info("✓ Processing thread finished")

    # Stop BladeRF
    logger.info("Step 2: Stopping BladeRF hardware")
    bladerf.stop_streaming()
    logger.info("✓ BladeRF stopped")

    # Notify client
    emit('status_update', {'streaming': False})
    logger.info("=" * 70)
    logger.info("✓ Streaming stopped")
    logger.info("=" * 70)


@socketio.on('set_frequency')
def handle_set_frequency(data):
    """
    Set center frequency via WebSocket command.

    Expected data format: {'frequency': <freq_in_hz>}
    """
    try:
        freq = float(data['frequency'])
        logger.info(f"Frequency change request from {request.sid}: {freq/1e6:.3f} MHz")

        if bladerf.set_frequency(freq):
            emit('status_update', {'center_freq': freq})
            logger.info(f"✓ Frequency updated successfully")
        else:
            logger.error("✗ Failed to set frequency")
            emit('error', {'message': 'Failed to set frequency - check range (20 MHz - 6 GHz)'})

    except KeyError:
        logger.error("Missing 'frequency' key in data")
        emit('error', {'message': 'Invalid request format'})
    except ValueError as e:
        logger.error(f"Invalid frequency value: {e}")
        emit('error', {'message': 'Invalid frequency value'})
    except Exception as e:
        logger.error(f"Unexpected error setting frequency: {e}", exc_info=True)
        emit('error', {'message': str(e)})


@socketio.on('set_gain')
def handle_set_gain(data):
    """
    Set RX gain via WebSocket command.

    Expected data format: {'gain': <gain_in_db>}
    """
    try:
        gain = float(data['gain'])
        logger.info(f"Gain change request from {request.sid}: {gain} dB")

        if bladerf.set_gain(gain):
            emit('status_update', {'gain': gain})
            logger.info(f"✓ Gain updated successfully")
        else:
            logger.error("✗ Failed to set gain")
            emit('error', {'message': 'Failed to set gain - check range (0-60 dB)'})

    except KeyError:
        logger.error("Missing 'gain' key in data")
        emit('error', {'message': 'Invalid request format'})
    except ValueError as e:
        logger.error(f"Invalid gain value: {e}")
        emit('error', {'message': 'Invalid gain value'})
    except Exception as e:
        logger.error(f"Unexpected error setting gain: {e}", exc_info=True)
        emit('error', {'message': str(e)})


@socketio.on('set_bandwidth')
def handle_set_bandwidth(data):
    """
    Set bandwidth via WebSocket command.

    Expected data format: {'bandwidth': <bandwidth_in_hz>}
    """
    try:
        bandwidth = float(data['bandwidth'])
        logger.info(f"Bandwidth change request from {request.sid}: {bandwidth/1e6:.3f} MHz")

        if bladerf.set_bandwidth(bandwidth):
            emit('status_update', {'bandwidth': bandwidth})
            logger.info(f"✓ Bandwidth updated successfully")
        else:
            logger.error("✗ Failed to set bandwidth")
            emit('error', {'message': 'Failed to set bandwidth'})

    except KeyError:
        logger.error("Missing 'bandwidth' key in data")
        emit('error', {'message': 'Invalid request format'})
    except ValueError as e:
        logger.error(f"Invalid bandwidth value: {e}")
        emit('error', {'message': 'Invalid bandwidth value'})
    except Exception as e:
        logger.error(f"Unexpected error setting bandwidth: {e}", exc_info=True)
        emit('error', {'message': str(e)})


@socketio.on('get_status')
def handle_get_status():
    """
    Send current device status to requesting client.
    """
    logger.debug(f"Status request from {request.sid}")

    if bladerf:
        status = bladerf.get_status()
        status['streaming'] = streaming_active
        logger.debug(f"Sending status: {status}")
        emit('status_update', status)
    else:
        logger.warning("BladeRF not initialized")
        emit('error', {'message': 'Hardware not initialized'})


def cleanup():
    """Cleanup resources on shutdown"""
    global streaming_active, bladerf

    logger.info("Cleaning up resources")

    streaming_active = False

    if bladerf:
        bladerf.cleanup()


if __name__ == '__main__':
    import atexit
    import socket

    # Register cleanup handler
    atexit.register(cleanup)

    logger.info("=" * 70)
    logger.info("SPECTRUM ANALYZER BACKEND")
    logger.info("=" * 70)

    # Initialize hardware
    if not init_hardware():
        logger.critical("✗ Failed to initialize hardware - cannot start server")
        sys.exit(1)

    # Get local IP for display
    try:
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
    except:
        local_ip = "unknown"

    # Run Flask app
    logger.info("=" * 70)
    logger.info("Starting Flask + Socket.IO server")
    logger.info(f"  Local:   http://localhost:5000")
    logger.info(f"  Network: http://{local_ip}:5000")
    logger.info("  Press Ctrl+C to stop")
    logger.info("=" * 70)

    try:
        socketio.run(app, host='0.0.0.0', port=5000, debug=False, log_output=True)
    except KeyboardInterrupt:
        logger.info("\nShutdown requested by user")
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
    finally:
        logger.info("Server stopped")
