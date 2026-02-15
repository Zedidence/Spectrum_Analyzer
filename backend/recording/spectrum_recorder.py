"""
Spectrum recorder: captures processed DSP snapshots to CSV.

Lightweight, throttled to ~1 Hz. Captures post-DSP spectrum data
for offline analysis without the storage cost of raw IQ.
"""

import time
import csv
import json
import logging
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


@dataclass
class SpectrumRecordingMeta:
    """Metadata for spectrum recordings."""
    filename: str
    sample_rate: float
    center_freq: float
    fft_size: int
    num_bins: int
    start_time: float
    end_time: float = 0.0
    total_frames: int = 0


class SpectrumRecorder:
    """
    Throttled spectrum data recorder.

    Called from the DSP thread. Internally throttles to capture_rate Hz.
    Writes CSV: timestamp, center_freq, sample_rate, noise_floor,
    peak_power, peak_freq_offset, bin_0..bin_N.
    """

    def __init__(self, config):
        self._config = config
        self._storage_path = Path(config.storage_path)
        self._storage_path.mkdir(parents=True, exist_ok=True)

        self._recording = False
        self._file = None
        self._writer = None
        self._metadata: Optional[SpectrumRecordingMeta] = None
        self._meta_path = None
        self._last_capture = 0.0
        self._capture_interval = 1.0 / config.spectrum_rate
        self._frame_count = 0

    @property
    def is_recording(self):
        return self._recording

    def start(self, sample_rate, center_freq, fft_size):
        """Begin spectrum recording. Returns filename or None."""
        if self._recording:
            return None

        ts = time.strftime("%Y%m%d_%H%M%S")
        freq_mhz = center_freq / 1e6
        base_name = f"spectrum_{ts}_{freq_mhz:.3f}MHz"
        csv_path = self._storage_path / f"{base_name}.csv"
        meta_path = self._storage_path / f"{base_name}.json"

        try:
            self._file = open(csv_path, 'w', newline='')
            self._writer = csv.writer(self._file)
        except OSError as e:
            logger.error("Failed to open spectrum file: %s", e)
            return None

        self._meta_path = meta_path
        self._metadata = SpectrumRecordingMeta(
            filename=base_name,
            sample_rate=sample_rate,
            center_freq=center_freq,
            fft_size=fft_size,
            num_bins=0,
            start_time=time.time(),
        )
        self._frame_count = 0
        self._recording = True
        self._last_capture = 0.0

        logger.info("Spectrum recording started: %s", base_name)
        return base_name

    def capture(self, dsp_result, center_freq, sample_rate):
        """
        Capture a spectrum frame if enough time has elapsed.

        Called from DSP thread. Internally throttled.
        """
        if not self._recording:
            return

        now = time.monotonic()
        if now - self._last_capture < self._capture_interval:
            return
        self._last_capture = now

        spectrum = dsp_result.spectrum

        # Write header on first frame
        if self._frame_count == 0:
            num_bins = len(spectrum)
            self._metadata.num_bins = num_bins
            header = ['timestamp', 'center_freq', 'sample_rate',
                      'noise_floor', 'peak_power', 'peak_freq_offset']
            header.extend([f'bin_{i}' for i in range(num_bins)])
            self._writer.writerow(header)

        # Write data row
        row = [
            f'{time.time():.6f}',
            f'{center_freq:.0f}',
            f'{sample_rate:.0f}',
            f'{dsp_result.noise_floor:.2f}',
            f'{dsp_result.peak_power:.2f}',
            f'{dsp_result.peak_freq_offset:.6f}',
        ]
        row.extend([f'{v:.2f}' for v in spectrum])
        self._writer.writerow(row)

        self._frame_count += 1

        # Flush periodically
        if self._frame_count % 10 == 0:
            self._file.flush()

    def stop(self):
        """Stop spectrum recording and finalize. Returns filename or None."""
        if not self._recording:
            return None

        self._recording = False

        if self._file:
            self._file.flush()
            self._file.close()
            self._file = None
        self._writer = None

        filename = None
        if self._metadata:
            self._metadata.end_time = time.time()
            self._metadata.total_frames = self._frame_count
            filename = self._metadata.filename
            try:
                with open(self._meta_path, 'w') as f:
                    json.dump(asdict(self._metadata), f, indent=2)
            except OSError as e:
                logger.error("Failed to write spectrum metadata: %s", e)

        logger.info("Spectrum recording stopped: %s (%d frames)",
                    filename, self._frame_count)
        self._metadata = None
        return filename

    def get_status(self):
        """Return current recording status."""
        return {
            'spectrum_recording': self._recording,
            'spectrum_frames': self._frame_count,
            'spectrum_filename': (
                self._metadata.filename if self._metadata else None
            ),
        }
