"""
IQ playback: replays recorded IQ data through the DSP pipeline.

Reads a .raw file (complex64) and feeds chunks into the iq_queue
at the original sample rate. The DSP pipeline processes replayed
data identically to live data.

Supports speed control (0.1x - 10x), pause/resume, and auto-loop.
"""

import threading
import queue
import logging
import time
import json
import numpy as np
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class PlaybackState:
    """Current playback state."""
    playing: bool = False
    paused: bool = False
    filename: str = ""
    position_bytes: int = 0
    total_bytes: int = 0
    position_seconds: float = 0.0
    duration_seconds: float = 0.0
    speed: float = 1.0
    loop: bool = False
    sample_rate: float = 0.0
    center_freq: float = 0.0


class IQPlayback:
    """
    File-based IQ data source that replaces BladeRF during playback.

    Feeds chunks into the existing iq_queue at real-time rate
    (adjustable via speed control).
    """

    def __init__(self, config):
        self._config = config
        self._storage_path = Path(config.storage_path)

        # Playback thread
        self._thread: Optional[threading.Thread] = None
        self._running = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()  # Start unpaused

        # Playback state
        self._state = PlaybackState()
        self._lock = threading.Lock()

        # Output queue (set during start)
        self._iq_queue: Optional[queue.Queue] = None

        # File state
        self._file = None
        self._metadata = None
        self._chunk_size = 2048

    @property
    def is_playing(self):
        return self._state.playing

    @property
    def is_paused(self):
        return self._state.paused

    def start(self, filename, iq_queue, chunk_size):
        """
        Begin playback of a recorded IQ file.

        Args:
            filename: Base filename (without extension)
            iq_queue: queue.Queue to feed IQ chunks into
            chunk_size: Samples per chunk (FFT size)

        Returns:
            Metadata dict or None on failure
        """
        if self._state.playing:
            logger.warning("Already playing")
            return None

        raw_path = self._storage_path / f"{filename}.raw"
        meta_path = self._storage_path / f"{filename}.json"

        # Load metadata
        try:
            with open(meta_path, 'r') as f:
                self._metadata = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.error("Failed to load playback metadata: %s", e)
            return None

        # Open raw file
        try:
            self._file = open(raw_path, 'rb')
        except OSError as e:
            logger.error("Failed to open playback file: %s", e)
            return None

        total_bytes = raw_path.stat().st_size
        sample_rate = self._metadata.get('sample_rate', 2e6)
        bytes_per_sample = 8  # complex64 = 2 * float32
        total_samples = total_bytes // bytes_per_sample
        duration = total_samples / sample_rate

        self._iq_queue = iq_queue
        self._chunk_size = chunk_size

        with self._lock:
            self._state = PlaybackState(
                playing=True,
                paused=False,
                filename=filename,
                position_bytes=0,
                total_bytes=total_bytes,
                position_seconds=0.0,
                duration_seconds=duration,
                speed=1.0,
                loop=False,
                sample_rate=sample_rate,
                center_freq=self._metadata.get('center_freq', 100e6),
            )

        self._pause_event.set()
        self._running.set()
        self._thread = threading.Thread(
            target=self._playback_loop,
            name="iq-playback-thread",
            daemon=True,
        )
        self._thread.start()

        logger.info("Playback started: %s (%.1f s, %.2f MS/s)",
                     filename, duration, sample_rate / 1e6)
        return self._metadata

    def stop(self):
        """Stop playback."""
        if not self._state.playing:
            return

        self._running.clear()
        self._pause_event.set()  # Unblock if paused

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)

        if self._file:
            self._file.close()
            self._file = None

        with self._lock:
            self._state.playing = False
            self._state.paused = False

        self._thread = None
        logger.info("Playback stopped")

    def pause(self):
        """Pause playback."""
        if self._state.playing and not self._state.paused:
            self._pause_event.clear()
            with self._lock:
                self._state.paused = True
            logger.info("Playback paused")

    def resume(self):
        """Resume playback."""
        if self._state.playing and self._state.paused:
            self._pause_event.set()
            with self._lock:
                self._state.paused = False
            logger.info("Playback resumed")

    def set_speed(self, speed):
        """Set playback speed (0.1x to 10x)."""
        speed = max(0.1, min(10.0, float(speed)))
        with self._lock:
            self._state.speed = speed
        logger.info("Playback speed: %.1fx", speed)

    def set_loop(self, loop):
        """Enable/disable auto-loop at EOF."""
        with self._lock:
            self._state.loop = bool(loop)

    def seek(self, position_seconds):
        """Seek to a position in the recording."""
        if not self._state.playing or not self._file:
            return

        bytes_per_sample = 8
        sample_rate = self._state.sample_rate
        target_sample = int(position_seconds * sample_rate)
        target_byte = target_sample * bytes_per_sample

        # Align to chunk boundary
        chunk_bytes = self._chunk_size * bytes_per_sample
        target_byte = (target_byte // chunk_bytes) * chunk_bytes
        target_byte = max(0, min(target_byte, self._state.total_bytes))

        # Protect file seek and state update under the same lock
        with self._lock:
            self._file.seek(target_byte)
            self._state.position_bytes = target_byte
            self._state.position_seconds = (
                target_byte / bytes_per_sample / sample_rate
            )

    def _playback_loop(self):
        """Playback thread: reads file, paces output."""
        logger.info("Playback thread started")

        bytes_per_sample = 8  # complex64
        chunk_bytes = self._chunk_size * bytes_per_sample
        sample_rate = self._state.sample_rate

        # Time per chunk at 1x speed
        base_chunk_interval = self._chunk_size / sample_rate

        while self._running.is_set():
            # Handle pause
            self._pause_event.wait(timeout=0.5)
            if not self._running.is_set():
                break
            if not self._pause_event.is_set():
                continue

            with self._lock:
                speed = self._state.speed
            chunk_interval = base_chunk_interval / speed

            t0 = time.monotonic()

            # Read chunk (under lock to coordinate with seek())
            with self._lock:
                raw_bytes = self._file.read(chunk_bytes)

            if len(raw_bytes) < chunk_bytes:
                # EOF
                with self._lock:
                    if self._state.loop:
                        self._file.seek(0)
                        self._state.position_bytes = 0
                        self._state.position_seconds = 0.0
                        logger.info("Playback: looping to start")
                        continue
                    else:
                        self._state.playing = False
                        logger.info("Playback: reached end of file")
                        break

            # Convert to complex64 numpy array
            iq_chunk = np.frombuffer(raw_bytes, dtype=np.complex64).copy()

            # Feed into iq_queue
            try:
                self._iq_queue.put(iq_chunk, timeout=2.0)
            except queue.Full:
                logger.warning("Playback: iq_queue full, dropping chunk")
                continue

            # Update position
            with self._lock:
                self._state.position_bytes += chunk_bytes
                self._state.position_seconds = (
                    self._state.position_bytes / bytes_per_sample / sample_rate
                )

            # Pace to real-time
            elapsed = time.monotonic() - t0
            sleep_time = chunk_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

        self._running.clear()
        with self._lock:
            self._state.playing = False
        logger.info("Playback thread exited")

    def get_status(self):
        """Return playback state for status API."""
        with self._lock:
            return {
                'playback_active': self._state.playing,
                'playback_paused': self._state.paused,
                'playback_filename': self._state.filename,
                'playback_position': self._state.position_seconds,
                'playback_duration': self._state.duration_seconds,
                'playback_speed': self._state.speed,
                'playback_loop': self._state.loop,
                'playback_progress': (
                    self._state.position_bytes / self._state.total_bytes
                    if self._state.total_bytes > 0 else 0.0
                ),
                'playback_sample_rate': self._state.sample_rate,
                'playback_center_freq': self._state.center_freq,
            }
