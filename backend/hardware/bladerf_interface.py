"""
BladeRF hardware interface using GNU Radio + osmosdr.

THREADING MODEL:
- All GNU Radio operations happen in a single dedicated native thread.
- IQ data flows out via a threading.Queue (native, never monkey-patched).
- Parameter changes (freq, gain) use osmosdr's thread-safe setters.
- No eventlet anywhere in this module.
"""

import threading
import queue
import logging
import time
import numpy as np

from gnuradio import gr
from osmosdr import source as osmosdr_source

logger = logging.getLogger(__name__)


class DataSink(gr.sync_block):
    """
    Custom GNU Radio sink that deposits FFT-sized chunks into a Queue.

    work() is called from GNU Radio's C++ scheduler thread.
    Uses only native (non-patched) queue operations.
    """

    def __init__(self, chunk_size, output_queue):
        gr.sync_block.__init__(
            self,
            name="iq_data_sink",
            in_sig=[np.complex64],
            out_sig=None,
        )
        self._chunk_size = chunk_size
        self._queue = output_queue
        self._buffer = np.empty(0, dtype=np.complex64)
        self._drop_count = 0
        self._last_drop_log = 0.0
        self._sample_count = 0

    def work(self, input_items, output_items):
        samples = input_items[0]
        n = len(samples)
        self._sample_count += n

        # Accumulate into buffer, emit chunk_size blocks
        self._buffer = np.concatenate([self._buffer, samples])

        while len(self._buffer) >= self._chunk_size:
            chunk = self._buffer[:self._chunk_size].copy()
            self._buffer = self._buffer[self._chunk_size:]

            try:
                self._queue.put_nowait(chunk)
            except queue.Full:
                self._drop_count += 1
                now = time.monotonic()
                if now - self._last_drop_log >= 5.0:
                    logger.warning(
                        "IQ queue full, dropped %d chunks in last 5s",
                        self._drop_count,
                    )
                    self._drop_count = 0
                    self._last_drop_log = now

        return n


class BladeRFInterface:
    """
    High-level BladeRF interface.

    Thread-safe parameter setters. Flowgraph runs in dedicated native thread.
    """

    def __init__(self, config):
        """
        Args:
            config: BladeRFConfig dataclass instance
        """
        self._config = config
        self._lock = threading.Lock()

        # Current parameters (protected by _lock)
        self._center_freq = config.center_freq
        self._sample_rate = config.sample_rate
        self._bandwidth = config.bandwidth
        self._gain = config.gain

        # GNU Radio objects (only touched by flowgraph thread + start/stop)
        self._flowgraph = None
        self._sdr_source = None
        self._data_sink = None
        self._thread = None
        self._running = threading.Event()

        # Chunk size set by StreamManager before start()
        self._chunk_size = 2048

        # Output queue: set by start()
        self._iq_queue = None

        logger.info(
            "BladeRFInterface initialized: freq=%.3f MHz, rate=%.2f MS/s, gain=%.0f dB",
            self._center_freq / 1e6,
            self._sample_rate / 1e6,
            self._gain,
        )

    @property
    def iq_queue(self):
        return self._iq_queue

    def set_chunk_size(self, size):
        """Set FFT chunk size (call before start)."""
        self._chunk_size = size

    def start(self, iq_queue):
        """
        Build flowgraph and start streaming in a background thread.

        Args:
            iq_queue: threading.Queue for IQ data output

        Returns:
            True if started successfully.
        """
        if self._running.is_set():
            logger.warning("Already running")
            return False

        self._iq_queue = iq_queue

        try:
            self._build_flowgraph()
        except Exception:
            logger.error("Failed to build flowgraph", exc_info=True)
            self._destroy_flowgraph()
            return False

        self._running.set()
        self._thread = threading.Thread(
            target=self._run_flowgraph,
            name="gnuradio-thread",
            daemon=True,
        )
        self._thread.start()
        logger.info("Streaming started")
        return True

    def stop(self):
        """Stop streaming and destroy flowgraph."""
        if not self._running.is_set():
            return

        logger.info("Stopping streaming...")
        self._running.clear()

        # Stop flowgraph FIRST (unblocks the thread)
        if self._flowgraph:
            try:
                self._flowgraph.stop()
            except Exception as e:
                logger.debug("Flowgraph stop exception: %s", e)

        # Then join thread
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
            if self._thread.is_alive():
                logger.warning("GNU Radio thread did not exit in 5s")

        self._destroy_flowgraph()
        self._thread = None
        logger.info("Streaming stopped")

    def _build_flowgraph(self):
        """Create GNU Radio flowgraph."""
        self._destroy_flowgraph()

        self._flowgraph = gr.top_block("bladerf_rx")
        self._sdr_source = osmosdr_source(self._config.device_string)

        # Apply parameters
        self._sdr_source.set_sample_rate(self._sample_rate)
        self._sdr_source.set_center_freq(self._center_freq, 0)
        self._sdr_source.set_gain(self._gain, 0)
        self._sdr_source.set_bandwidth(self._bandwidth, 0)
        self._sdr_source.set_gain_mode(self._config.gain_mode, 0)
        self._sdr_source.set_freq_corr(0)

        # DataSink writes chunks to the IQ queue
        self._data_sink = DataSink(self._chunk_size, self._iq_queue)
        self._flowgraph.connect(self._sdr_source, self._data_sink)

        logger.info(
            "Flowgraph built: freq=%.3f MHz, rate=%.2f MS/s, gain=%.0f dB, chunk=%d",
            self._center_freq / 1e6,
            self._sample_rate / 1e6,
            self._gain,
            self._chunk_size,
        )

    def _run_flowgraph(self):
        """Flowgraph execution thread (native thread, not eventlet)."""
        try:
            self._flowgraph.start()
            logger.info("GNU Radio flowgraph running")

            # Block until signaled to stop
            while self._running.is_set():
                self._running.wait(timeout=1.0)

        except Exception:
            logger.error("Flowgraph thread error", exc_info=True)
        finally:
            if self._flowgraph:
                try:
                    self._flowgraph.stop()
                    self._flowgraph.wait()
                except Exception:
                    pass
            logger.info("GNU Radio thread exited")

    def _destroy_flowgraph(self):
        """Release GNU Radio resources."""
        if self._flowgraph:
            try:
                self._flowgraph.stop()
                self._flowgraph.wait()
            except Exception:
                pass

        self._flowgraph = None
        self._sdr_source = None
        self._data_sink = None

    # --- Thread-safe parameter setters ---

    def set_frequency(self, freq_hz):
        with self._lock:
            if not (self._config.min_freq <= freq_hz <= self._config.max_freq):
                logger.warning(
                    "Frequency %.3f MHz out of range [%.1f - %.1f MHz]",
                    freq_hz / 1e6,
                    self._config.min_freq / 1e6,
                    self._config.max_freq / 1e6,
                )
                return False
            old = self._center_freq
            self._center_freq = freq_hz
            if self._sdr_source and self._running.is_set():
                self._sdr_source.set_center_freq(freq_hz, 0)
                logger.info("Frequency: %.3f -> %.3f MHz", old / 1e6, freq_hz / 1e6)
            return True

    def set_gain(self, gain_db):
        with self._lock:
            gain_db = max(self._config.min_gain, min(self._config.max_gain, gain_db))
            old = self._gain
            self._gain = gain_db
            if self._sdr_source and self._running.is_set():
                self._sdr_source.set_gain(gain_db, 0)
                logger.info("Gain: %.0f -> %.0f dB", old, gain_db)
            return True

    def set_sample_rate(self, rate_hz):
        with self._lock:
            if not (self._config.min_sample_rate <= rate_hz <= self._config.max_sample_rate):
                logger.warning("Sample rate %.2f MS/s out of range", rate_hz / 1e6)
                return False
            old = self._sample_rate
            self._sample_rate = rate_hz
            if self._sdr_source and self._running.is_set():
                self._sdr_source.set_sample_rate(rate_hz)
                logger.info("Sample rate: %.2f -> %.2f MS/s", old / 1e6, rate_hz / 1e6)
            return True

    def set_bandwidth(self, bw_hz):
        with self._lock:
            old = self._bandwidth
            self._bandwidth = bw_hz
            if self._sdr_source and self._running.is_set():
                self._sdr_source.set_bandwidth(bw_hz, 0)
                logger.info("Bandwidth: %.3f -> %.3f MHz", old / 1e6, bw_hz / 1e6)
            return True

    def get_status(self):
        with self._lock:
            return {
                'center_freq': self._center_freq,
                'sample_rate': self._sample_rate,
                'bandwidth': self._bandwidth,
                'gain': self._gain,
                'running': self._running.is_set(),
            }

    def cleanup(self):
        """Full cleanup: stop streaming and release resources."""
        self.stop()
        self._destroy_flowgraph()
