"""
Peak-preserving downsampler for spectrum display.

For spectrum analyzers, we want to preserve signal peaks (not average
them away). Strategy: for each output bin, take the MAX of the
corresponding input bins. This matches "peak detect" mode on
commercial spectrum analyzers.
"""

import numpy as np


class Downsampler:
    """Peak-preserving spectrum downsampler."""

    def __init__(self, target_bins):
        """
        Args:
            target_bins: Target number of output bins
        """
        self._target = target_bins

    def downsample(self, spectrum):
        """
        Downsample spectrum data using peak-preserving decimation.

        Handles non-integer ratios by mapping each output bin to a
        floating-point range of input bins, ensuring the full spectrum
        is covered without truncation.

        Args:
            spectrum: float32 numpy array of power values

        Returns:
            float32 numpy array of downsampled values
        """
        n = len(spectrum)
        if n <= self._target:
            return spectrum

        # Use floating-point bin mapping to cover the entire input range
        result = np.empty(self._target, dtype=np.float32)
        ratio = n / self._target
        for i in range(self._target):
            start = int(i * ratio)
            end = int((i + 1) * ratio)
            end = max(end, start + 1)  # At least one bin
            result[i] = np.max(spectrum[start:end])

        return result

    @property
    def target_bins(self):
        return self._target

    @target_bins.setter
    def target_bins(self, value):
        self._target = value
