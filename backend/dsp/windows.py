"""
Window functions for FFT processing.

Each window has different trade-offs:
- Hanning: Good general purpose, -31 dB sidelobes
- Blackman-Harris: Excellent sidelobe suppression, -92 dB
- Flat-top: Best amplitude accuracy, wider main lobe
- Kaiser: Tunable via beta parameter
- Rectangular: No windowing (maximum resolution, worst leakage)
"""

import numpy as np
from scipy.signal import windows as scipy_windows

WINDOW_FUNCTIONS = {
    "hanning": np.hanning,
    "hamming": np.hamming,
    "blackman": np.blackman,
    "blackman-harris": lambda n: scipy_windows.blackmanharris(n),
    "flat-top": lambda n: scipy_windows.flattop(n),
    "kaiser-6": lambda n: np.kaiser(n, 6.0),
    "kaiser-10": lambda n: np.kaiser(n, 10.0),
    "kaiser-14": lambda n: np.kaiser(n, 14.0),
    "rectangular": lambda n: np.ones(n),
}


def get_window(name, size):
    """
    Get window function as float32 array.

    Args:
        name: Window function name (see WINDOW_FUNCTIONS keys)
        size: Window length in samples

    Returns:
        numpy float32 array of window values
    """
    if name not in WINDOW_FUNCTIONS:
        raise ValueError(
            f"Unknown window: {name}. Options: {list(WINDOW_FUNCTIONS.keys())}"
        )
    return WINDOW_FUNCTIONS[name](size).astype(np.float32)


def window_correction_factor(window):
    """
    Compute coherent power gain correction factor.

    This normalizes the FFT output so that a full-scale sine wave
    reads correctly in dBFS.

    Args:
        window: numpy array of window values

    Returns:
        float correction factor (sum(window)^2)
    """
    return float(np.sum(window) ** 2)


def available_windows():
    """Return list of available window function names."""
    return list(WINDOW_FUNCTIONS.keys())
