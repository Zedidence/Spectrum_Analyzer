"""
Signal processing pipeline.

Converts IQ samples to display-ready power spectrum.

Pipeline stages:
1. DC offset removal (IIR high-pass)
2. Overlap-save accumulation (50% overlap)
3. Windowing
4. FFT (pyFFTW or NumPy)
5. Power spectrum (magnitude squared -> dBFS)
6. Averaging (none / linear / exponential)
7. Peak hold update
8. Noise floor estimation
9. Downsampling for display
"""

import numpy as np
import logging
from collections import deque
from typing import Optional
from dataclasses import dataclass, field

from dsp.windows import get_window, window_correction_factor
from dsp.dc_removal import DCRemover
from dsp.downsampler import Downsampler

logger = logging.getLogger(__name__)

# Try pyFFTW first, fall back to NumPy
try:
    import pyfftw
    pyfftw.interfaces.cache.enable()
    HAS_PYFFTW = True
except ImportError:
    HAS_PYFFTW = False


@dataclass
class DSPResult:
    """Output of the DSP pipeline for one frame."""
    spectrum: np.ndarray        # float32, power in dBFS
    peak_hold: Optional[np.ndarray]  # float32, peak hold trace (or None)
    noise_floor: float          # estimated noise floor in dB
    peak_freq_offset: float     # peak bin position normalized [-0.5, 0.5]
    peak_power: float           # peak power in dBFS


class DSPPipeline:
    """
    Complete DSP pipeline from IQ samples to display-ready spectrum.
    """

    def __init__(self, config):
        """
        Args:
            config: DSPConfig dataclass
        """
        self._config = config
        self._fft_size = config.fft_size

        # Window function
        self._window_type = config.window_type
        self._window = get_window(config.window_type, config.fft_size)
        self._window_correction = window_correction_factor(self._window)

        # DC removal
        self._dc_remover = DCRemover() if config.dc_removal else None

        # Overlap-save buffer (50% overlap)
        self._overlap_enabled = True
        self._overlap_buffer = None  # Will hold previous half-block

        # FFT setup
        if HAS_PYFFTW:
            self._fft_in = pyfftw.empty_aligned(config.fft_size, dtype='complex64')
            self._fft_out = pyfftw.empty_aligned(config.fft_size, dtype='complex64')
            self._fft_plan = pyfftw.FFTW(
                self._fft_in, self._fft_out,
                direction='FFTW_FORWARD',
                flags=('FFTW_MEASURE',),
                threads=config.pyfftw_threads,
            )
            logger.info("Using pyFFTW with %d threads", config.pyfftw_threads)
        else:
            self._fft_in = None
            self._fft_out = None
            self._fft_plan = None
            logger.info("Using NumPy FFT")

        # Averaging state
        self._avg_mode = config.averaging_mode
        self._avg_count = config.averaging_count
        self._avg_alpha = config.averaging_alpha
        self._avg_buffer = deque(maxlen=config.averaging_count)
        self._ema_state: Optional[np.ndarray] = None

        # Peak hold state
        self._peak_hold_enabled = False
        self._peak_hold_state: Optional[np.ndarray] = None
        self._peak_hold_decay = 0.0  # 0 = infinite hold, >0 = decay per frame in dB

        # Noise floor estimation (running percentile)
        self._noise_samples = deque(maxlen=64)

        # Downsampler
        self._downsampler = Downsampler(config.target_display_bins)

        logger.info(
            "DSP pipeline: fft=%d, window=%s, avg=%s, dc_removal=%s, overlap=50%%",
            config.fft_size,
            config.window_type,
            config.averaging_mode,
            config.dc_removal,
        )

    def process(self, iq_chunk):
        """
        Process one FFT-sized chunk of IQ data through the pipeline.

        With overlap enabled, accumulates samples and produces FFT blocks
        with 50% overlap for better spectral estimation.

        Args:
            iq_chunk: complex64 numpy array (length = fft_size)

        Returns:
            DSPResult or None if input is wrong size or accumulating overlap
        """
        if len(iq_chunk) != self._fft_size:
            logger.warning(
                "IQ chunk size %d != FFT size %d", len(iq_chunk), self._fft_size
            )
            return None

        # Stage 1: DC offset removal
        if self._dc_remover:
            iq_chunk = self._dc_remover.remove(iq_chunk)

        # Stage 2: Overlap-save accumulation
        if self._overlap_enabled:
            results = self._process_with_overlap(iq_chunk)
            if results is None:
                return None
            # Average the overlapped FFT results
            power_dbfs = np.mean(results, axis=0)
        else:
            power_dbfs = self._compute_spectrum(iq_chunk)

        # Stage 5: Averaging
        spectrum = self._apply_averaging(power_dbfs)

        # Stage 6: Peak hold update (before downsample for full resolution)
        peak_hold_full = self._update_peak_hold(spectrum)

        # Stage 7: Noise floor estimation
        noise_floor = self._estimate_noise_floor(spectrum)

        # Stage 8: Downsample for display
        display_spectrum = self._downsampler.downsample(spectrum)
        display_peak_hold = None
        if peak_hold_full is not None:
            display_peak_hold = self._downsampler.downsample(peak_hold_full)

        # Find peak
        peak_idx = np.argmax(display_spectrum)
        peak_power = float(display_spectrum[peak_idx])
        num_bins = len(display_spectrum)
        peak_freq_offset = (peak_idx - num_bins / 2) / num_bins

        return DSPResult(
            spectrum=display_spectrum,
            peak_hold=display_peak_hold,
            noise_floor=noise_floor,
            peak_freq_offset=peak_freq_offset,
            peak_power=peak_power,
        )

    def _process_with_overlap(self, iq_chunk):
        """
        Overlap-save: combine current chunk with previous half to produce
        two overlapping FFT blocks.

        Returns array of dBFS spectra (shape: [N, fft_size]) or None if
        still accumulating the first block.
        """
        half = self._fft_size // 2

        if self._overlap_buffer is None:
            # First chunk: process it directly, save second half for overlap
            self._overlap_buffer = iq_chunk[half:].copy()
            return np.array([self._compute_spectrum(iq_chunk)])

        # Build overlapped block: last half of previous + first half of current
        overlapped = np.concatenate([self._overlap_buffer, iq_chunk[:half]])

        # Save second half of current chunk for next overlap
        self._overlap_buffer = iq_chunk[half:].copy()

        # Compute spectra for both blocks
        spec_overlap = self._compute_spectrum(overlapped)
        spec_current = self._compute_spectrum(iq_chunk)

        return np.array([spec_overlap, spec_current])

    def _compute_spectrum(self, samples):
        """
        Compute power spectrum in dBFS from IQ samples.

        Args:
            samples: complex64 array of length fft_size

        Returns:
            float32 array of power in dBFS
        """
        # Windowing
        windowed = samples * self._window

        # FFT
        if self._fft_plan is not None:
            self._fft_in[:] = windowed
            self._fft_plan()
            fft_result = np.fft.fftshift(self._fft_out).copy()
        else:
            fft_result = np.fft.fftshift(np.fft.fft(windowed))

        # Power spectrum in dBFS
        power = np.abs(fft_result) ** 2
        power = np.maximum(power, 1e-20)
        normalization = self._fft_size ** 2 * self._window_correction
        if normalization > 0:
            return (10.0 * np.log10(power / normalization)).astype(np.float32)
        else:
            return (10.0 * np.log10(power)).astype(np.float32)

    def _apply_averaging(self, power_dbfs):
        if self._avg_mode == "none":
            return power_dbfs

        elif self._avg_mode == "linear":
            self._avg_buffer.append(power_dbfs.copy())
            return np.mean(self._avg_buffer, axis=0, dtype=np.float32)

        elif self._avg_mode == "exponential":
            if self._ema_state is None:
                self._ema_state = power_dbfs.copy()
            else:
                alpha = self._avg_alpha
                self._ema_state = alpha * power_dbfs + (1 - alpha) * self._ema_state
            return self._ema_state.copy()

        return power_dbfs

    def _update_peak_hold(self, spectrum):
        """Update peak hold trace. Returns peak hold array or None if disabled."""
        if not self._peak_hold_enabled:
            return None

        if self._peak_hold_state is None:
            self._peak_hold_state = spectrum.copy()
        else:
            if self._peak_hold_decay > 0:
                # Decay existing peaks
                self._peak_hold_state -= self._peak_hold_decay
            # Take element-wise maximum
            self._peak_hold_state = np.maximum(
                self._peak_hold_state, spectrum
            )

        return self._peak_hold_state.copy()

    def _estimate_noise_floor(self, spectrum):
        """Estimate noise floor as 10th percentile of spectrum."""
        p10 = float(np.percentile(spectrum, 10))
        self._noise_samples.append(p10)
        return float(np.median(self._noise_samples))

    def set_param(self, key, value):
        """Dynamically update DSP parameters."""
        if key == "window_type" and value != self._window_type:
            self._window_type = value
            self._window = get_window(value, self._fft_size)
            self._window_correction = window_correction_factor(self._window)
            logger.info("Window changed to %s", value)
        elif key == "averaging_mode":
            self._avg_mode = value
            self._ema_state = None
            self._avg_buffer.clear()
            logger.info("Averaging mode changed to %s", value)
        elif key == "averaging_count":
            self._avg_count = int(value)
            self._avg_buffer = deque(maxlen=self._avg_count)
        elif key == "averaging_alpha":
            self._avg_alpha = float(value)
        elif key == "dc_removal":
            if value and not self._dc_remover:
                self._dc_remover = DCRemover()
            elif not value:
                self._dc_remover = None
        elif key == "peak_hold":
            self._peak_hold_enabled = bool(value)
            if not value:
                self._peak_hold_state = None
            logger.info("Peak hold %s", "enabled" if value else "disabled")
        elif key == "peak_hold_decay":
            self._peak_hold_decay = float(value)
        elif key == "peak_hold_reset":
            self._peak_hold_state = None
            logger.info("Peak hold reset")

    def reset(self):
        """Reset all accumulated state."""
        self._avg_buffer.clear()
        self._ema_state = None
        self._noise_samples.clear()
        self._overlap_buffer = None
        self._peak_hold_state = None
        if self._dc_remover:
            self._dc_remover.reset()

    @property
    def fft_size(self):
        return self._fft_size
