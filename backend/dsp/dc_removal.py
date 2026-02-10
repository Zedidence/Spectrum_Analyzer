"""
DC offset removal using a single-pole IIR high-pass filter.

Removes the DC spike at center frequency caused by I/Q imbalance
and ADC offset in the BladeRF.

Transfer function: H(z) = (1 - z^-1) / (1 - alpha * z^-1)
With alpha = 0.9999, the -3dB point is ~0.016 Hz at 1 MS/s.
"""

import numpy as np
from scipy.signal import lfilter


class DCRemover:
    """IIR high-pass filter for DC removal using scipy lfilter."""

    def __init__(self, alpha=0.9999):
        self._alpha = alpha
        # Filter coefficients: b = [1, -1], a = [1, -alpha]
        self._b = np.array([1.0, -1.0], dtype=np.float64)
        self._a = np.array([1.0, -self._alpha], dtype=np.float64)
        # Filter state for continuity between blocks
        # lfilter_zi would give steady-state, but we start from zero
        self._zi_real = np.zeros(1, dtype=np.float64)
        self._zi_imag = np.zeros(1, dtype=np.float64)

    def remove(self, samples):
        """
        Apply DC removal to a block of complex samples.

        Args:
            samples: numpy complex64 array

        Returns:
            DC-removed complex64 array
        """
        # Process real and imaginary parts separately through IIR filter
        out_real, self._zi_real = lfilter(
            self._b, self._a,
            samples.real.astype(np.float64),
            zi=self._zi_real,
        )
        out_imag, self._zi_imag = lfilter(
            self._b, self._a,
            samples.imag.astype(np.float64),
            zi=self._zi_imag,
        )

        return (out_real + 1j * out_imag).astype(np.complex64)

    def reset(self):
        """Reset filter state."""
        self._zi_real = np.zeros(1, dtype=np.float64)
        self._zi_imag = np.zeros(1, dtype=np.float64)
