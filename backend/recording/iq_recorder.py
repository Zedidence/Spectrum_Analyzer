"""
IQ data recorder: captures raw IQ samples from the DSP pipeline.

Runs a dedicated writer thread that reads from a recording queue
and writes to disk with 512 KB buffered I/O. Never blocks the DSP thread.

Output: .raw (complex64 binary) + .json (metadata sidecar)
"""

import threading
import queue
import logging
import time
import json
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, asdict

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class RecordingMetadata:
    """Metadata sidecar for IQ recordings."""
    filename: str
    format: str                    # "complex64"
    sample_rate: float             # Hz
    center_freq: float             # Hz
    bandwidth: float               # Hz
    gain: float                    # dB
    fft_size: int
    start_time: float              # Unix timestamp
    end_time: float = 0.0
    total_samples: int = 0
    total_bytes: int = 0
    duration_seconds: float = 0.0


class IQRecorder:
    """
    Buffered IQ data writer with dedicated thread.

    Usage:
        recorder = IQRecorder(config)
        recorder.start(sample_rate, center_freq, bandwidth, gain, fft_size)
        # From DSP thread: recorder.put(iq_chunk)
        recorder.stop()
    """

    def __init__(self, config):
        self._config = config
        self._storage_path = Path(config.storage_path)
        self._storage_path.mkdir(parents=True, exist_ok=True)

        # Writer thread state
        self._thread: Optional[threading.Thread] = None
        self._running = threading.Event()
        self._queue: Optional[queue.Queue] = None

        # Recording state
        self._recording = False
        self._metadata: Optional[RecordingMetadata] = None
        self._file = None
        self._meta_path = None
        self._bytes_written = 0
        self._samples_written = 0
        self._initial_usage = 0
        self._max_bytes = config.max_storage_bytes

    @property
    def is_recording(self):
        return self._recording

    @property
    def bytes_written(self):
        return self._bytes_written

    def start(self, sample_rate, center_freq, bandwidth, gain, fft_size):
        """
        Begin recording IQ data.

        Creates output files and starts the writer thread.
        Returns the recording filename (without extension) or None on failure.
        """
        if self._recording:
            logger.warning("Already recording")
            return None

        # Generate filename
        ts = time.strftime("%Y%m%d_%H%M%S")
        freq_mhz = center_freq / 1e6
        base_name = f"iq_{ts}_{freq_mhz:.3f}MHz"
        raw_path = self._storage_path / f"{base_name}.raw"
        meta_path = self._storage_path / f"{base_name}.json"

        # Check storage limits (total usage, not just this recording)
        current_usage = self._get_storage_usage()
        if current_usage >= self._max_bytes:
            logger.error("Storage limit reached: %d / %d bytes",
                         current_usage, self._max_bytes)
            return None
        self._initial_usage = current_usage

        self._metadata = RecordingMetadata(
            filename=base_name,
            format="complex64",
            sample_rate=sample_rate,
            center_freq=center_freq,
            bandwidth=bandwidth,
            gain=gain,
            fft_size=fft_size,
            start_time=time.time(),
        )

        # Open file with buffered writer
        try:
            self._file = open(raw_path, 'wb',
                              buffering=self._config.iq_buffer_size)
        except OSError as e:
            logger.error("Failed to open recording file: %s", e)
            return None

        self._meta_path = meta_path
        self._bytes_written = 0
        self._samples_written = 0

        # Create recording queue
        self._queue = queue.Queue(maxsize=self._config.iq_queue_size)

        # Start writer thread
        self._running.set()
        self._recording = True
        self._thread = threading.Thread(
            target=self._writer_loop,
            name="iq-recorder-thread",
            daemon=True,
        )
        self._thread.start()

        logger.info("IQ recording started: %s (%.3f MHz, %.2f MS/s)",
                     base_name, freq_mhz, sample_rate / 1e6)
        return base_name

    def put(self, iq_chunk):
        """
        Submit an IQ chunk for recording.

        Called from the DSP thread. Non-blocking: drops if queue full.
        """
        if not self._recording or self._queue is None:
            return

        try:
            self._queue.put_nowait(iq_chunk)
        except queue.Full:
            pass  # Drop rather than block DSP thread

    def stop(self):
        """Stop recording and finalize files."""
        if not self._recording:
            return None

        self._recording = False
        self._running.clear()

        # Wait for writer thread to drain queue and exit
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
            if self._thread.is_alive():
                logger.warning("IQ recorder thread did not exit in 5s")

        # Close file
        if self._file:
            self._file.flush()
            self._file.close()
            self._file = None

        # Finalize metadata
        filename = None
        if self._metadata:
            self._metadata.end_time = time.time()
            self._metadata.total_samples = self._samples_written
            self._metadata.total_bytes = self._bytes_written
            self._metadata.duration_seconds = (
                self._metadata.end_time - self._metadata.start_time
            )
            filename = self._metadata.filename

            try:
                with open(self._meta_path, 'w') as f:
                    json.dump(asdict(self._metadata), f, indent=2)
            except OSError as e:
                logger.error("Failed to write metadata: %s", e)

        logger.info(
            "IQ recording stopped: %s (%d samples, %d bytes, %.1f s)",
            filename,
            self._samples_written,
            self._bytes_written,
            self._metadata.duration_seconds if self._metadata else 0,
        )

        self._metadata = None
        self._thread = None
        return filename

    def _writer_loop(self):
        """Writer thread: reads from queue, writes to file."""
        logger.info("IQ recorder thread started")

        while self._running.is_set() or not self._queue.empty():
            try:
                chunk = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            raw_bytes = chunk.astype(np.complex64).tobytes()
            try:
                self._file.write(raw_bytes)
                self._bytes_written += len(raw_bytes)
                self._samples_written += len(chunk)
            except OSError as e:
                logger.error("IQ write error: %s", e)
                self._running.clear()
                break

            # Check storage limit (total usage including other recordings)
            if self._bytes_written + self._initial_usage >= self._max_bytes:
                logger.warning("Storage limit reached, auto-stopping recording")
                self._recording = False
                self._running.clear()
                break

        logger.info("IQ recorder thread exited (%d bytes written)",
                    self._bytes_written)

    def _get_storage_usage(self):
        """Calculate total bytes used in storage directory."""
        total = 0
        try:
            for f in self._storage_path.iterdir():
                if f.is_file():
                    total += f.stat().st_size
        except OSError:
            pass
        return total

    def get_status(self):
        """Return current recording status."""
        return {
            'iq_recording': self._recording,
            'iq_bytes_written': self._bytes_written,
            'iq_samples_written': self._samples_written,
            'iq_duration': (
                time.time() - self._metadata.start_time
                if self._metadata else 0.0
            ),
            'iq_filename': (
                self._metadata.filename if self._metadata else None
            ),
        }
