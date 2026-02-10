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

        Args:
            spectrum: float32 numpy array of power values

        Returns:
            float32 numpy array of downsampled values
        """
        n = len(spectrum)
        if n <= self._target:
            return spectrum

        # Peak-preserving decimation
        factor = n // self._target
        trimmed = spectrum[:self._target * factor]
        reshaped = trimmed.reshape(self._target, factor)
        return np.max(reshaped, axis=1).astype(np.float32)

    @property
    def target_bins(self):
        return self._target

    @target_bins.setter
    def target_bins(self, value):
        self._target = value
