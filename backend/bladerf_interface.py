"""
BladeRF Interface Module
Controls BladeRF SDR via gr-osmosdr for spectrum analyzer application.

This module provides a high-level interface to the BladeRF SDR using GNU Radio
and gr-osmosdr. It handles device initialization, IQ data streaming, and parameter
control (frequency, gain, bandwidth).
"""

import numpy as np
from gnuradio import gr, blocks
from osmosdr import source
import threading
import queue
import logging
import time

# Configure logging with detailed format
# Use INFO level for normal operation, change to DEBUG for troubleshooting
logging.basicConfig(
    level=logging.INFO,  # Changed from DEBUG to reduce log spam
    format='%(asctime)s - %(name)s - %(levelname)s - [%(funcName)s] %(message)s'
)
logger = logging.getLogger(__name__)


class DataSink(gr.sync_block):
    """
    Custom GNU Radio sink block that captures IQ data and puts it in a queue.

    This block is used instead of vector_sink because it provides better
    real-time performance for continuous streaming applications.
    """
    def __init__(self, fft_size, data_queue):
        """
        Initialize the data sink.

        Args:
            fft_size: Number of samples per FFT chunk
            data_queue: Python queue to put captured data
        """
        gr.sync_block.__init__(
            self,
            name="data_sink",
            in_sig=[np.complex64],  # Input: complex IQ samples
            out_sig=None  # Output: none (sink)
        )
        self.fft_size = fft_size
        self.data_queue = data_queue
        self.sample_count = 0
        self.drop_count = 0  # Track dropped samples
        self.last_drop_log = 0  # Timestamp of last drop log
        logger.debug(f"DataSink initialized with fft_size={fft_size}")

    def work(self, input_items, output_items):
        """
        Process incoming samples.

        This method is called by GNU Radio scheduler when data is available.
        It collects samples into FFT-sized chunks and puts them in the queue.
        """
        in0 = input_items[0]  # Get input samples
        num_samples = len(in0)

        # Update sample count
        self.sample_count += num_samples

        # Log periodic stats (every 100 FFT chunks processed)
        if self.sample_count % (self.fft_size * 100) == 0:
            logger.debug(f"DataSink: processed {self.sample_count} samples, queue size: {self.data_queue.qsize()}, drops: {self.drop_count}")

        # Process samples in FFT-sized chunks
        for i in range(0, num_samples, self.fft_size):
            if i + self.fft_size <= num_samples:
                chunk = in0[i:i + self.fft_size].copy()

                # Try to put in queue (non-blocking, drop if full)
                try:
                    self.data_queue.put(chunk, block=False)
                except queue.Full:
                    # Queue full - drop data
                    self.drop_count += 1

                    # Rate-limited logging: only log every 5 seconds
                    current_time = time.time()
                    if current_time - self.last_drop_log >= 5.0:
                        logger.warning(f"⚠ Queue full - dropped {self.drop_count} chunks (processing too slow)")
                        self.last_drop_log = current_time
                        self.drop_count = 0  # Reset counter

        return num_samples  # Tell GNU Radio we consumed all samples


class BladeRFInterface:
    """
    Interface to BladeRF SDR using GNU Radio and gr-osmosdr.

    This class manages the BladeRF device, handles data streaming, and provides
    methods for controlling device parameters (frequency, gain, bandwidth).
    """

    def __init__(self, sample_rate=2.4e6, fft_size=2048):
        """
        Initialize BladeRF interface.

        Args:
            sample_rate: Sample rate in Hz (default 2.4 MHz for <5 MHz bandwidth)
            fft_size: FFT size for processing (default 2048)
        """
        logger.info(f"Initializing BladeRFInterface: sample_rate={sample_rate/1e6:.1f} MS/s, fft_size={fft_size}")

        self.sample_rate = sample_rate
        self.fft_size = fft_size
        self.center_freq = 100e6  # Default to 100 MHz (FM radio)
        self.gain = 40  # Default gain in dB (increased from 30 for better signal visibility)
        self.bandwidth = 2e6  # Default bandwidth 2 MHz

        self.running = False
        self.flowgraph = None
        self.data_queue = queue.Queue(maxsize=20)  # Increased from 10 for better buffering
        self.thread = None
        self.sdr_source = None
        self.data_sink = None

        # Device parameters
        self.min_freq = 20e6  # 20 MHz (plan spec: 20 MHz - 6 GHz)
        self.max_freq = 6e9   # 6 GHz
        self.min_gain = 0     # BladeRF practical min gain (changed from -15)
        self.max_gain = 60    # BladeRF 2.0 max gain

        logger.info("BladeRFInterface initialized successfully")

    def setup_device(self):
        """
        Initialize BladeRF device and GNU Radio flowgraph.

        This creates the signal processing chain:
        BladeRF (osmosdr source) -> Custom Data Sink -> Queue

        Returns:
            bool: True if setup successful, False otherwise
        """
        try:
            logger.info("=" * 60)
            logger.info("Setting up BladeRF device")
            logger.info(f"  Sample rate: {self.sample_rate/1e6:.2f} MS/s")
            logger.info(f"  Center frequency: {self.center_freq/1e6:.2f} MHz")
            logger.info(f"  Gain: {self.gain} dB")
            logger.info(f"  Bandwidth: {self.bandwidth/1e6:.2f} MHz")
            logger.info(f"  FFT size: {self.fft_size}")
            logger.info("=" * 60)

            # Create GNU Radio flowgraph
            logger.debug("Creating GNU Radio top_block")
            self.flowgraph = gr.top_block()

            # Create osmosdr source for BladeRF
            logger.debug("Creating osmosdr source for BladeRF")
            self.sdr_source = source("bladerf=0")  # Use first BladeRF device

            # Configure BladeRF parameters
            logger.debug(f"Setting sample rate: {self.sample_rate/1e6:.2f} MS/s")
            self.sdr_source.set_sample_rate(self.sample_rate)

            logger.debug(f"Setting center frequency: {self.center_freq/1e6:.2f} MHz")
            self.sdr_source.set_center_freq(self.center_freq)

            logger.debug("Setting frequency correction: 0")
            self.sdr_source.set_freq_corr(0)  # No frequency correction

            logger.debug(f"Setting gain: {self.gain} dB")
            self.sdr_source.set_gain(self.gain, 0)  # Channel 0

            logger.debug(f"Setting bandwidth: {self.bandwidth/1e6:.2f} MHz")
            self.sdr_source.set_bandwidth(self.bandwidth, 0)  # Channel 0

            # Set gain mode to manual for consistent performance
            logger.debug("Setting gain mode to manual")
            self.sdr_source.set_gain_mode(False, 0)  # False = manual gain

            # Create custom data sink
            logger.debug(f"Creating custom DataSink block (fft_size={self.fft_size})")
            self.data_sink = DataSink(self.fft_size, self.data_queue)

            # Connect flowgraph: BladeRF -> DataSink
            logger.debug("Connecting flowgraph blocks")
            self.flowgraph.connect((self.sdr_source, 0), (self.data_sink, 0))

            logger.info("✓ BladeRF setup complete - ready to stream")
            return True

        except Exception as e:
            logger.error(f"✗ Failed to setup BladeRF: {e}", exc_info=True)
            return False

    def start_streaming(self):
        """
        Start IQ data streaming from BladeRF.

        This sets up the flowgraph and starts the GNU Radio processing thread.
        Data will be available via get_iq_data() method.

        Returns:
            bool: True if streaming started successfully, False otherwise
        """
        if self.running:
            logger.warning("⚠ Already streaming - ignoring start request")
            return False

        logger.info("Starting BladeRF streaming...")

        # Setup device and flowgraph
        if not self.setup_device():
            logger.error("✗ Failed to setup device - cannot start streaming")
            return False

        # Clear any old data from queue
        while not self.data_queue.empty():
            try:
                self.data_queue.get_nowait()
            except queue.Empty:
                break
        logger.debug("Cleared data queue")

        self.running = True

        # Start flowgraph in separate thread
        logger.debug("Starting streaming thread")
        self.thread = threading.Thread(target=self._streaming_thread, daemon=True)
        self.thread.start()

        logger.info("✓ Streaming started successfully")
        return True

    def _streaming_thread(self):
        """
        Thread that runs the GNU Radio flowgraph.

        This thread starts the flowgraph and keeps it running until
        stop_streaming() is called. The custom DataSink block automatically
        fills the data queue as samples arrive.
        """
        try:
            logger.info("Streaming thread started")

            # Start GNU Radio flowgraph
            logger.debug("Starting GNU Radio flowgraph")
            self.flowgraph.start()
            logger.info("✓ Flowgraph running - data should be flowing")

            # Monitor flowgraph while running
            check_count = 0
            last_queue_size = 0

            while self.running:
                # Periodic status checks (every 5 seconds)
                if check_count % 500 == 0:  # 500 * 10ms = 5 seconds
                    queue_size = self.data_queue.qsize()
                    logger.info(f"Status: Queue size = {queue_size}, Queue delta = {queue_size - last_queue_size}")

                    if queue_size == 0 and check_count > 100:
                        logger.warning("⚠ Queue is empty - no data being received!")
                        logger.warning("  Possible causes:")
                        logger.warning("  - BladeRF not connected properly")
                        logger.warning("  - USB connection issue")
                        logger.warning("  - Driver problem")

                    last_queue_size = queue_size

                check_count += 1
                time.sleep(0.01)  # 10ms sleep

            # Stop flowgraph gracefully
            logger.info("Stopping flowgraph...")
            self.flowgraph.stop()
            self.flowgraph.wait()
            logger.info("✓ Flowgraph stopped")

        except Exception as e:
            logger.error(f"✗ Error in streaming thread: {e}", exc_info=True)
            self.running = False

    def stop_streaming(self):
        """
        Stop IQ data streaming.

        This gracefully stops the GNU Radio flowgraph and cleans up resources.
        """
        if not self.running:
            logger.debug("Not running - nothing to stop")
            return

        logger.info("Stopping streaming...")
        self.running = False

        # Wait for thread to finish
        if self.thread:
            logger.debug("Waiting for streaming thread to finish...")
            self.thread.join(timeout=3.0)
            if self.thread.is_alive():
                logger.warning("⚠ Streaming thread did not finish in time")
            else:
                logger.debug("✓ Streaming thread finished")

        # Stop flowgraph if still running
        if self.flowgraph:
            try:
                logger.debug("Stopping flowgraph")
                self.flowgraph.stop()
                self.flowgraph.wait()
                logger.debug("✓ Flowgraph stopped")
            except Exception as e:
                logger.warning(f"Error stopping flowgraph: {e}")

        logger.info("✓ Streaming stopped")

    def get_iq_data(self, timeout=1.0):
        """
        Get IQ data chunk from queue.

        This method blocks until data is available or timeout occurs.
        The data is collected by the GNU Radio flowgraph and the custom
        DataSink block.

        Args:
            timeout: Timeout in seconds (default 1.0)

        Returns:
            numpy array of complex IQ samples (length=fft_size), or None if timeout
        """
        try:
            data = self.data_queue.get(timeout=timeout)
            # Debug: log data stats occasionally
            if np.random.random() < 0.01:  # Log 1% of the time to avoid spam
                logger.debug(f"Got IQ data: shape={data.shape}, mean_power={np.mean(np.abs(data)**2):.2e}")
            return data
        except queue.Empty:
            logger.debug(f"Queue timeout after {timeout}s - no data available")
            return None

    def set_frequency(self, freq_hz):
        """
        Set center frequency.

        This tunes the BladeRF to receive at the specified frequency.
        Changes take effect immediately if streaming is active.

        Args:
            freq_hz: Frequency in Hz (must be within min_freq to max_freq range)

        Returns:
            bool: True if successful, False otherwise
        """
        # Validate frequency range
        if not (self.min_freq <= freq_hz <= self.max_freq):
            logger.warning(f"⚠ Frequency {freq_hz/1e6:.1f} MHz out of range "
                          f"[{self.min_freq/1e6:.1f} - {self.max_freq/1e3:.1f} MHz]")
            return False

        # Update stored frequency
        old_freq = self.center_freq
        self.center_freq = freq_hz

        # Apply to hardware if streaming
        if self.sdr_source and self.running:
            try:
                self.sdr_source.set_center_freq(freq_hz, 0)  # Channel 0
                logger.info(f"✓ Frequency: {old_freq/1e6:.3f} MHz → {freq_hz/1e6:.3f} MHz")
                return True
            except Exception as e:
                logger.error(f"✗ Failed to set frequency: {e}", exc_info=True)
                return False
        else:
            logger.debug(f"Frequency updated to {freq_hz/1e6:.3f} MHz (will apply when streaming starts)")
            return True

    def set_gain(self, gain_db):
        """
        Set RX gain.

        Higher gain amplifies weak signals but may cause saturation on strong signals.
        Lower gain reduces sensitivity but prevents overload.

        Args:
            gain_db: Gain in dB (will be clamped to valid range)

        Returns:
            bool: True if successful, False otherwise
        """
        # Clamp to valid range
        old_gain = self.gain
        gain_db = max(self.min_gain, min(self.max_gain, gain_db))
        self.gain = gain_db

        if gain_db != old_gain:
            logger.debug(f"Gain clamped: {old_gain} dB → {gain_db} dB")

        # Apply to hardware if streaming
        if self.sdr_source and self.running:
            try:
                self.sdr_source.set_gain(gain_db, 0)  # Channel 0
                logger.info(f"✓ Gain: {old_gain} dB → {gain_db} dB")
                return True
            except Exception as e:
                logger.error(f"✗ Failed to set gain: {e}", exc_info=True)
                return False
        else:
            logger.debug(f"Gain updated to {gain_db} dB (will apply when streaming starts)")
            return True

    def set_bandwidth(self, bw_hz):
        """
        Set bandwidth (analog filter bandwidth).

        The bandwidth filter determines how much spectrum around the center
        frequency is captured. Should typically match or slightly exceed
        the sample rate for best performance.

        Args:
            bw_hz: Bandwidth in Hz

        Returns:
            bool: True if successful, False otherwise
        """
        old_bw = self.bandwidth
        self.bandwidth = bw_hz

        # Apply to hardware if streaming
        if self.sdr_source and self.running:
            try:
                self.sdr_source.set_bandwidth(bw_hz, 0)  # Channel 0
                logger.info(f"✓ Bandwidth: {old_bw/1e6:.3f} MHz → {bw_hz/1e6:.3f} MHz")
                return True
            except Exception as e:
                logger.error(f"✗ Failed to set bandwidth: {e}", exc_info=True)
                return False
        else:
            logger.debug(f"Bandwidth updated to {bw_hz/1e6:.3f} MHz (will apply when streaming starts)")
            return True

    def get_status(self):
        """
        Get current device status.

        Returns:
            dict with device parameters
        """
        return {
            'center_freq': self.center_freq,
            'sample_rate': self.sample_rate,
            'gain': self.gain,
            'bandwidth': self.bandwidth,
            'running': self.running,
            'fft_size': self.fft_size
        }

    def cleanup(self):
        """Cleanup resources"""
        self.stop_streaming()
