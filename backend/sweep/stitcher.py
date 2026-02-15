"""
Spectrum stitcher for panoramic sweep display.

Takes individual FFT segments from sweep steps and assembles them into
a single continuous panoramic spectrum. Handles edge trimming and
raised-cosine crossfade blending in overlap regions.
"""

import numpy as np
import logging

from dsp.downsampler import Downsampler

logger = logging.getLogger(__name__)


def compute_step_frequencies(freq_start, freq_end, sample_rate, usable_fraction):
    """
    Compute center frequencies for each sweep step.

    Steps advance by usable_bw so that the usable portions tile
    contiguously from freq_start to freq_end.

    Args:
        freq_start: Start frequency (Hz)
        freq_end: End frequency (Hz)
        sample_rate: Sample rate during sweep (Hz)
        usable_fraction: Fraction of bandwidth to keep (0.0-1.0)

    Returns:
        List of center frequencies (Hz)
    """
    usable_bw = sample_rate * usable_fraction
    half_bw = sample_rate / 2

    steps = []
    # First center: place so left edge of usable band aligns with freq_start
    current_center = freq_start + usable_bw / 2
    while current_center - usable_bw / 2 < freq_end:
        # Clamp to BladeRF range
        clamped = max(47e6 + half_bw, min(6e9 - half_bw, current_center))
        steps.append(clamped)
        current_center += usable_bw

    if not steps:
        steps.append((freq_start + freq_end) / 2)

    return steps


class SpectrumStitcher:
    """
    Assembles sweep segments into a stitched panoramic spectrum.

    Each sweep step produces an FFT power spectrum centered at its
    step frequency. The stitcher trims the filter rolloff edges,
    maps bins to absolute frequencies, and blends overlaps with
    a raised-cosine crossfade.
    """

    def __init__(self, freq_start, freq_end, step_frequencies,
                 sample_rate, fft_size, usable_fraction):
        """
        Args:
            freq_start: Overall sweep start frequency (Hz)
            freq_end: Overall sweep end frequency (Hz)
            step_frequencies: List of center frequencies for each step
            sample_rate: Sample rate during sweep (Hz)
            fft_size: FFT size used per step
            usable_fraction: Fraction of bandwidth to keep per step
        """
        self._freq_start = freq_start
        self._freq_end = freq_end
        self._steps = step_frequencies
        self._sample_rate = sample_rate
        self._fft_size = fft_size
        self._usable_fraction = usable_fraction
        self._num_steps = len(step_frequencies)

        # Per-step parameters
        self._usable_bw = sample_rate * usable_fraction
        trim_fraction = (1.0 - usable_fraction) / 2
        self._trim_bins = int(fft_size * trim_fraction)
        self._usable_bins = fft_size - 2 * self._trim_bins

        # Build panorama frequency map
        self._build_panorama()

        logger.info(
            "Stitcher: %d steps, %d usable bins/step, %d total panorama bins, "
            "%.3f - %.3f MHz",
            self._num_steps, self._usable_bins, self._panorama_bins,
            freq_start / 1e6, freq_end / 1e6,
        )

    def _build_panorama(self):
        """Pre-compute panorama array size and bin-to-frequency mapping."""
        self._panorama_bins = self._usable_bins * self._num_steps
        self._panorama = np.full(self._panorama_bins, -200.0, dtype=np.float32)
        self._panorama_freqs = np.zeros(self._panorama_bins, dtype=np.float64)

        # Map each panorama bin to its absolute frequency
        for step_idx, center_freq in enumerate(self._steps):
            start_bin = step_idx * self._usable_bins
            step_freq_start = center_freq - self._usable_bw / 2
            bin_width = self._sample_rate / self._fft_size

            for b in range(self._usable_bins):
                abs_bin = self._trim_bins + b
                self._panorama_freqs[start_bin + b] = (
                    center_freq - self._sample_rate / 2 + abs_bin * bin_width
                )

        # Build crossfade windows for overlap blending
        # For adjacent steps, the overlap region is where step N's right usable
        # edge overlaps with step N+1's left usable edge. Since we tile by
        # usable_bw, there's no actual overlap in the stitched array — but
        # we still apply edge tapering to smooth any discontinuities.
        self._edge_taper_len = min(32, self._usable_bins // 4)
        if self._edge_taper_len > 0:
            taper = np.linspace(0, 1, self._edge_taper_len, dtype=np.float32)
            self._left_taper = taper
            self._right_taper = taper[::-1]

    def add_segment(self, step_idx, power_spectrum):
        """
        Insert a step's spectrum into the panorama.

        Args:
            step_idx: Index of this step (0-based)
            power_spectrum: float32 array of power values (dBFS), length = fft_size
        """
        if step_idx < 0 or step_idx >= self._num_steps:
            return

        # Trim edges (remove filter rolloff)
        usable = power_spectrum[self._trim_bins:self._trim_bins + self._usable_bins]

        # Apply edge tapering for smooth transitions between segments
        segment = usable.copy()
        if self._edge_taper_len > 0:
            # Taper left edge (blend from previous segment in linear power domain)
            if step_idx > 0:
                left = self._edge_taper_len
                prev_start = step_idx * self._usable_bins - left
                if prev_start >= 0:
                    prev_edge = self._panorama[prev_start:step_idx * self._usable_bins]
                    if len(prev_edge) == left and np.all(prev_edge > -190):
                        # Convert to linear, blend, convert back to dB
                        prev_lin = np.power(10.0, prev_edge / 10.0)
                        curr_lin = np.power(10.0, segment[:left] / 10.0)
                        blended = self._right_taper * prev_lin + self._left_taper * curr_lin
                        segment[:left] = (10.0 * np.log10(np.maximum(blended, 1e-20))).astype(np.float32)

            # Taper right edge (pre-taper so next segment's blend is correct)
            if step_idx < self._num_steps - 1:
                right = self._edge_taper_len
                segment[-right:] = segment[-right:] * self._right_taper + \
                    segment[-right:] * (1.0 - self._right_taper)

        # Place into panorama
        start = step_idx * self._usable_bins
        self._panorama[start:start + self._usable_bins] = segment

    def get_panorama(self):
        """
        Return the full-resolution stitched panorama.

        Returns:
            (frequencies, powers) - both numpy arrays
        """
        return self._panorama_freqs.copy(), self._panorama.copy()

    def get_display_panorama(self, target_bins):
        """
        Return peak-preserving downsampled panorama for display.

        Args:
            target_bins: Number of output bins

        Returns:
            (frequencies, powers) - downsampled numpy arrays
        """
        if self._panorama_bins <= target_bins:
            return self.get_panorama()

        downsampler = Downsampler(target_bins)
        display_power = downsampler.downsample(self._panorama)

        # Downsample frequencies (take center of each bin group)
        factor = self._panorama_bins // target_bins
        trimmed_freqs = self._panorama_freqs[:target_bins * factor]
        reshaped = trimmed_freqs.reshape(target_bins, factor)
        display_freqs = np.mean(reshaped, axis=1)

        return display_freqs, display_power

    def reset(self):
        """Clear panorama for next sweep pass."""
        self._panorama[:] = -200.0

    @property
    def panorama_bins(self):
        return self._panorama_bins

    @property
    def num_steps(self):
        return self._num_steps

    @property
    def freq_start(self):
        return self._freq_start

    @property
    def freq_end(self):
        return self._freq_end
