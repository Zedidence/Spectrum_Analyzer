"""
Software Automatic Gain Control (AGC).

Adjusts hardware gain to keep signal level near a target dBFS.
Uses hysteresis to prevent oscillation and rate limiting to avoid
rapid gain changes.

Algorithm:
  1. Measure peak power from DSP result
  2. If peak > target + hysteresis/2: decrease gain
  3. If peak < target - hysteresis/2: increase gain
  4. Limit gain change rate (max one step per interval)
  5. Clamp gain to hardware limits [0, 60] dB
"""

import time
import logging

logger = logging.getLogger(__name__)


class SoftwareAGC:
    """Software AGC that commands hardware gain changes."""

    def __init__(
        self,
        target_dbfs=-20.0,
        hysteresis=6.0,
        gain_step=3.0,
        min_interval=1.0,
        gain_min=0.0,
        gain_max=60.0,
    ):
        """
        Args:
            target_dbfs: Target peak power level in dBFS
            hysteresis: Dead band width in dB (no adjustment within +/- half)
            gain_step: Gain adjustment step size in dB
            min_interval: Minimum time between adjustments in seconds
            gain_min: Minimum hardware gain in dB
            gain_max: Maximum hardware gain in dB
        """
        self._target = target_dbfs
        self._hysteresis = hysteresis
        self._gain_step = gain_step
        self._min_interval = min_interval
        self._gain_min = gain_min
        self._gain_max = gain_max

        self._enabled = False
        self._last_adjust_time = 0.0
        self._current_gain = 40.0

    @property
    def enabled(self):
        return self._enabled

    @enabled.setter
    def enabled(self, value):
        self._enabled = bool(value)
        if value:
            logger.info(
                "AGC enabled: target=%.0f dBFS, hysteresis=%.0f dB, step=%.0f dB",
                self._target, self._hysteresis, self._gain_step,
            )
        else:
            logger.info("AGC disabled")

    def update(self, peak_power, current_gain):
        """
        Evaluate whether gain needs adjustment.

        Args:
            peak_power: Current peak power in dBFS from DSP
            current_gain: Current hardware gain in dB

        Returns:
            float or None: New gain value, or None if no change needed
        """
        if not self._enabled:
            return None

        self._current_gain = current_gain
        now = time.monotonic()

        # Rate limiting
        if now - self._last_adjust_time < self._min_interval:
            return None

        half_hyst = self._hysteresis / 2.0
        error = peak_power - self._target

        if error > half_hyst:
            # Signal too strong, reduce gain
            new_gain = current_gain - self._gain_step
        elif error < -half_hyst:
            # Signal too weak, increase gain
            new_gain = current_gain + self._gain_step
        else:
            # Within dead band
            return None

        # Clamp to hardware limits
        new_gain = max(self._gain_min, min(self._gain_max, new_gain))

        if new_gain == current_gain:
            return None

        self._last_adjust_time = now
        logger.debug(
            "AGC: peak=%.1f dBFS, target=%.1f, gain %.0f -> %.0f dB",
            peak_power, self._target, current_gain, new_gain,
        )
        return new_gain

    def set_param(self, key, value):
        """Update AGC parameters dynamically."""
        if key == 'target_dbfs':
            self._target = float(value)
        elif key == 'hysteresis':
            self._hysteresis = float(value)
        elif key == 'gain_step':
            self._gain_step = float(value)
        elif key == 'min_interval':
            self._min_interval = float(value)
