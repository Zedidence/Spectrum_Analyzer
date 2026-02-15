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
class SweepConfig:
    """Frequency sweep configuration."""
    mode: str = "survey"             # "survey" or "band_monitor"
    freq_start: float = 47e6         # Hz
    freq_end: float = 6e9            # Hz
    sweep_sample_rate: float = 20e6  # Hz (sample rate during sweep)
    fft_size: int = 2048
    usable_fraction: float = 0.8     # Fraction of BW to use (trim edges)
    settle_chunks: int = 10          # FFT chunks to discard after retune
    averages_per_step: int = 4       # FFT averages per step
    display_bins: int = 4096         # Downsampled panorama bin count
    continuous: bool = False         # True for band_monitor mode


@dataclass
class DetectionConfig:
    """Signal detection configuration."""
    threshold_db: float = 6.0            # dB above noise floor to detect
    min_bandwidth_bins: int = 3          # Minimum bins for a valid signal
    merge_gap_bins: int = 5              # Merge regions separated by this many bins
    update_interval: float = 0.5         # Seconds between detection runs
    persistence_timeout: float = 10.0    # Seconds before a signal is marked lost
    overlap_match_ratio: float = 0.3     # Frequency overlap to consider same signal
    max_tracked_signals: int = 200       # Maximum simultaneously tracked signals


@dataclass
class RecordingConfig:
    """Recording and playback configuration."""
    storage_path: str = "data/recordings"
    max_storage_bytes: int = 1_073_741_824  # 1 GB
    iq_buffer_size: int = 524_288           # 512 KB write buffer
    iq_queue_size: int = 512
    spectrum_rate: float = 1.0              # Spectrum capture Hz


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
    sweep: SweepConfig = field(default_factory=SweepConfig)
    detection: DetectionConfig = field(default_factory=DetectionConfig)
    recording: RecordingConfig = field(default_factory=RecordingConfig)
