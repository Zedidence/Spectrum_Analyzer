"""
Application configuration with validation.

All magic numbers live here. Dataclass-based for type safety and defaults.
"""

from dataclasses import dataclass, field


@dataclass
class BladeRFConfig:
    """BladeRF hardware configuration."""
    device_string: str = "bladerf=0"
    center_freq: float = 100e6       # 100 MHz default (FM radio)
    sample_rate: float = 2e6         # 2 MS/s
    bandwidth: float = 2e6           # 2 MHz
    gain: float = 40.0               # dB
    gain_mode: bool = False          # False = manual
    min_freq: float = 47e6           # BladeRF 2.0 actual min
    max_freq: float = 6e9            # BladeRF 2.0 max
    min_gain: float = 0.0
    max_gain: float = 60.0
    min_sample_rate: float = 1e6     # 1 MS/s minimum for reliable operation
    max_sample_rate: float = 61.44e6


@dataclass
class DSPConfig:
    """DSP pipeline configuration."""
    fft_size: int = 2048
    window_type: str = "blackman-harris"
    averaging_mode: str = "exponential"  # "none", "linear", "exponential"
    averaging_count: int = 8              # For linear mode
    averaging_alpha: float = 0.3          # For exponential mode
    dc_removal: bool = True
    target_display_bins: int = 2048       # After downsampling
    pyfftw_threads: int = 2               # For RPi5


@dataclass
class Config:
    """Top-level application configuration."""
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 5000
    iq_queue_size: int = 256          # ~128ms buffer at 2MS/s, 1024 FFT
    result_queue_size: int = 8        # Small, we only need latest
    target_fps: int = 60
    bladerf: BladeRFConfig = field(default_factory=BladeRFConfig)
    dsp: DSPConfig = field(default_factory=DSPConfig)
