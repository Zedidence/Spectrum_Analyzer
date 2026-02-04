"""
Signal Processing Module
Handles FFT computation, windowing, and power spectrum calculation
for spectrum analyzer application.
"""

import numpy as np
import logging

# Try to use pyFFTW for better performance
try:
    import pyfftw
    pyfftw.interfaces.cache.enable()
    USE_PYFFTW = True
    logger = logging.getLogger(__name__)
    logger.info("Using pyFFTW for FFT computation")
except ImportError:
    USE_PYFFTW = False
    logger = logging.getLogger(__name__)
    logger.info("pyFFTW not available, using NumPy FFT")

logger = logging.getLogger(__name__)


class SignalProcessor:
    """Processes IQ samples to generate power spectrum"""

    def __init__(self, fft_size=2048, sample_rate=2.4e6, averaging=4):
        """
        Initialize signal processor.

        Args:
            fft_size: FFT size (number of bins)
            sample_rate: Sample rate in Hz
            averaging: Number of FFTs to average (1 = no averaging)
        """
        self.fft_size = fft_size
        self.sample_rate = sample_rate
        self.averaging = averaging

        # Pre-allocate arrays for performance
        self.window = self._create_window()
        self.fft_input = np.zeros(fft_size, dtype=np.complex64)
        self.fft_output = np.zeros(fft_size, dtype=np.complex64)

        # Running average buffer
        self.avg_buffer = []

        # Setup pyFFTW if available
        if USE_PYFFTW:
            self._setup_pyfftw()

    def _create_window(self):
        """Create window function for FFT (Hanning window)"""
        return np.hanning(self.fft_size).astype(np.float32)

    def _setup_pyfftw(self):
        """Setup pyFFTW for optimized FFT computation"""
        try:
            # Create FFTW object for repeated FFT calls
            self.fftw_object = pyfftw.FFTW(
                self.fft_input,
                self.fft_output,
                direction='FFTW_FORWARD',
                flags=('FFTW_MEASURE',),  # Measure and optimize
                threads=2  # Use 2 threads on Pi 5
            )
            logger.info("pyFFTW initialized with FFTW_MEASURE and 2 threads")
        except Exception as e:
            logger.warning(f"Failed to setup pyFFTW: {e}, falling back to NumPy")
            global USE_PYFFTW
            USE_PYFFTW = False

    def compute_fft(self, iq_samples):
        """
        Compute FFT of IQ samples with windowing.

        Args:
            iq_samples: Complex IQ samples (numpy array)

        Returns:
            FFT result (complex numpy array)
        """
        # Ensure correct size
        if len(iq_samples) != self.fft_size:
            logger.warning(f"IQ samples size {len(iq_samples)} != FFT size {self.fft_size}")
            return None

        # Apply window
        windowed = iq_samples * self.window

        # Compute FFT
        if USE_PYFFTW and hasattr(self, 'fftw_object'):
            # Copy to input buffer
            self.fft_input[:] = windowed
            # Execute FFT
            self.fftw_object()
            fft_result = self.fft_output.copy()
        else:
            # Use NumPy FFT
            fft_result = np.fft.fft(windowed)

        # FFT shift to center DC component
        fft_result = np.fft.fftshift(fft_result)

        return fft_result

    def compute_power_spectrum(self, fft_result):
        """
        Convert FFT result to power spectrum in dB.

        Args:
            fft_result: FFT result (complex array)

        Returns:
            Power spectrum in dB (float array)
        """
        # Compute magnitude squared
        power = np.abs(fft_result) ** 2

        # Avoid log(0) by setting minimum value
        power = np.maximum(power, 1e-20)

        # Convert to dB
        power_db = 10 * np.log10(power)

        return power_db

    def process_iq_samples(self, iq_samples):
        """
        Process IQ samples to power spectrum with averaging.

        Args:
            iq_samples: Complex IQ samples

        Returns:
            Power spectrum in dB, or None if not ready
        """
        # Compute FFT
        fft_result = self.compute_fft(iq_samples)
        if fft_result is None:
            return None

        # Compute power spectrum
        power_db = self.compute_power_spectrum(fft_result)

        # Apply averaging if enabled
        if self.averaging > 1:
            self.avg_buffer.append(power_db)

            # Keep only last N spectra
            if len(self.avg_buffer) > self.averaging:
                self.avg_buffer.pop(0)

            # Average if we have enough samples
            if len(self.avg_buffer) == self.averaging:
                power_db = np.mean(self.avg_buffer, axis=0)
            else:
                # Not enough samples yet for full average
                return None

        return power_db

    def get_frequency_bins(self, center_freq):
        """
        Get frequency values for each FFT bin.

        Args:
            center_freq: Center frequency in Hz

        Returns:
            Array of frequency values in Hz
        """
        freqs = np.fft.fftshift(np.fft.fftfreq(self.fft_size, 1/self.sample_rate))
        return freqs + center_freq

    def downsample_spectrum(self, spectrum, target_bins=1024):
        """
        Downsample spectrum for display efficiency.

        Args:
            spectrum: Power spectrum array
            target_bins: Target number of bins (default 1024)

        Returns:
            Downsampled spectrum
        """
        if len(spectrum) <= target_bins:
            return spectrum

        # Simple decimation by averaging
        factor = len(spectrum) // target_bins
        downsampled = np.mean(
            spectrum[:target_bins * factor].reshape(target_bins, factor),
            axis=1
        )

        return downsampled

    def set_averaging(self, averaging):
        """
        Set averaging factor.

        Args:
            averaging: Number of FFTs to average
        """
        self.averaging = max(1, averaging)
        self.avg_buffer = []
        logger.info(f"Set averaging to {self.averaging}")

    def reset_averaging(self):
        """Reset averaging buffer"""
        self.avg_buffer = []

    def get_statistics(self, spectrum):
        """
        Compute statistics from power spectrum.

        Args:
            spectrum: Power spectrum in dB

        Returns:
            dict with statistics (max, min, mean, peak_freq)
        """
        if spectrum is None or len(spectrum) == 0:
            return None

        return {
            'max_power': float(np.max(spectrum)),
            'min_power': float(np.min(spectrum)),
            'mean_power': float(np.mean(spectrum)),
            'peak_bin': int(np.argmax(spectrum)),
            'std_dev': float(np.std(spectrum))
        }
