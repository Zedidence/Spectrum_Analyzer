"""
Signal detector: finds active transmissions above the noise floor.

Runs inside the DSP thread at a throttled rate. Identifies contiguous
regions of the spectrum above a configurable threshold, tracks them
across frames, and generates signal_new / signal_update / signal_lost
events that are bridged to the asyncio event loop.
"""

import time
import logging
import numpy as np
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class DetectedSignal:
    """A currently tracked signal."""
    signal_id: int
    center_freq: float          # Hz
    peak_freq: float            # Hz
    bandwidth: float            # Hz (estimated)
    peak_power: float           # dBFS
    avg_power: float            # dBFS
    bin_start: int              # Start bin index
    bin_end: int                # End bin index (exclusive)
    first_seen: float           # time.monotonic()
    last_seen: float            # time.monotonic()
    hit_count: int = 1
    classification: str = ""
    notes: str = ""


@dataclass
class SignalEvent:
    """Event emitted when signal state changes."""
    event_type: str             # "signal_new", "signal_update", "signal_lost"
    signal: DetectedSignal


class SignalDetector:
    """
    Spectrum-based signal detector with tracking.

    Call `detect()` from the DSP thread with each processed spectrum.
    Internally throttled to run at `update_interval` rate.
    """

    def __init__(self, config):
        """
        Args:
            config: DetectionConfig dataclass instance
        """
        self._config = config
        self._enabled = False

        # Tracking state
        self._tracked: Dict[int, DetectedSignal] = {}
        self._next_id = 1
        self._last_detect_time = 0.0

        # Event buffer (consumed by streaming manager)
        self._events: List[SignalEvent] = []

        # Detection statistics
        self._total_detections = 0

    @property
    def enabled(self):
        return self._enabled

    @enabled.setter
    def enabled(self, value):
        self._enabled = bool(value)
        if not value:
            # Emit lost events for all tracked signals
            for sig in list(self._tracked.values()):
                self._events.append(SignalEvent("signal_lost", sig))
            self._tracked.clear()
        logger.info("Signal detection %s", "enabled" if value else "disabled")

    def detect(self, spectrum, noise_floor, center_freq, sample_rate):
        """
        Run detection on a spectrum frame.

        Called from DSP thread. Internally throttled to config.update_interval.

        Args:
            spectrum: float32 array of power in dBFS (display bins)
            noise_floor: estimated noise floor in dB
            center_freq: current center frequency in Hz
            sample_rate: current sample rate in Hz

        Returns:
            List of SignalEvent (may be empty)
        """
        if not self._enabled:
            return []

        now = time.monotonic()
        if now - self._last_detect_time < self._config.update_interval:
            return []
        self._last_detect_time = now

        # Find regions above threshold
        threshold = noise_floor + self._config.threshold_db
        regions = self._find_regions(spectrum, threshold)

        # Characterize each region
        current_signals = []
        num_bins = len(spectrum)
        freq_start = center_freq - sample_rate / 2
        bin_width = sample_rate / num_bins

        for (start_bin, end_bin) in regions:
            segment = spectrum[start_bin:end_bin]
            peak_bin = start_bin + int(np.argmax(segment))

            sig_center_freq = freq_start + (start_bin + end_bin - 1) / 2 * bin_width
            sig_peak_freq = freq_start + peak_bin * bin_width
            sig_bandwidth = (end_bin - start_bin) * bin_width
            sig_peak_power = float(segment.max())
            # Average in linear power domain, then convert back to dB
            sig_avg_power = float(10.0 * np.log10(
                np.mean(np.power(10.0, segment / 10.0))
            ))

            current_signals.append({
                'center_freq': sig_center_freq,
                'peak_freq': sig_peak_freq,
                'bandwidth': sig_bandwidth,
                'peak_power': sig_peak_power,
                'avg_power': sig_avg_power,
                'bin_start': start_bin,
                'bin_end': end_bin,
            })

        # Match against tracked signals
        events = self._match_and_track(current_signals, now)

        # Check for lost signals
        lost = []
        for sig_id, sig in self._tracked.items():
            if now - sig.last_seen > self._config.persistence_timeout:
                lost.append(sig_id)
                events.append(SignalEvent("signal_lost", sig))

        for sig_id in lost:
            del self._tracked[sig_id]

        self._events.extend(events)
        return events

    def drain_events(self):
        """Return and clear pending events. Thread-safe (called from same thread)."""
        events = self._events
        self._events = []
        return events

    def _find_regions(self, spectrum, threshold):
        """
        Find contiguous regions above threshold.

        Returns list of (start_bin, end_bin) tuples.
        """
        above = spectrum > threshold
        if not np.any(above):
            return []

        # Find transitions
        padded = np.concatenate([[False], above, [False]])
        diff = np.diff(padded.astype(int))
        starts = np.where(diff == 1)[0]
        ends = np.where(diff == -1)[0]

        # Filter by minimum width
        min_bins = self._config.min_bandwidth_bins
        regions = [(s, e) for s, e in zip(starts, ends) if e - s >= min_bins]

        # Merge close regions
        if len(regions) < 2:
            return regions

        merged = [regions[0]]
        gap = self._config.merge_gap_bins
        for s, e in regions[1:]:
            prev_s, prev_e = merged[-1]
            if s - prev_e <= gap:
                merged[-1] = (prev_s, e)
            else:
                merged.append((s, e))

        return merged

    def _match_and_track(self, current_signals, now):
        """
        Match detected signals against tracked signals using frequency overlap.

        Returns list of SignalEvents.
        """
        events = []
        matched_tracked = set()
        match_ratio = self._config.overlap_match_ratio

        for sig_data in current_signals:
            best_match = None
            best_overlap = 0

            # Try to match with existing tracked signals
            for sig_id, tracked in self._tracked.items():
                if sig_id in matched_tracked:
                    continue

                overlap = self._compute_overlap(
                    sig_data['bin_start'], sig_data['bin_end'],
                    tracked.bin_start, tracked.bin_end,
                )
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_match = sig_id

            if best_match is not None and best_overlap >= match_ratio:
                # Update existing signal
                tracked = self._tracked[best_match]
                tracked.center_freq = sig_data['center_freq']
                tracked.peak_freq = sig_data['peak_freq']
                tracked.bandwidth = sig_data['bandwidth']
                tracked.peak_power = sig_data['peak_power']
                tracked.avg_power = sig_data['avg_power']
                tracked.bin_start = sig_data['bin_start']
                tracked.bin_end = sig_data['bin_end']
                tracked.last_seen = now
                tracked.hit_count += 1
                matched_tracked.add(best_match)
                events.append(SignalEvent("signal_update", tracked))
            else:
                # New signal
                if len(self._tracked) >= self._config.max_tracked_signals:
                    continue  # Skip if at capacity

                sig = DetectedSignal(
                    signal_id=self._next_id,
                    center_freq=sig_data['center_freq'],
                    peak_freq=sig_data['peak_freq'],
                    bandwidth=sig_data['bandwidth'],
                    peak_power=sig_data['peak_power'],
                    avg_power=sig_data['avg_power'],
                    bin_start=sig_data['bin_start'],
                    bin_end=sig_data['bin_end'],
                    first_seen=now,
                    last_seen=now,
                )
                self._tracked[sig.signal_id] = sig
                self._next_id += 1
                self._total_detections += 1
                events.append(SignalEvent("signal_new", sig))

        return events

    def _compute_overlap(self, a_start, a_end, b_start, b_end):
        """Compute fractional overlap between two bin ranges."""
        overlap_start = max(a_start, b_start)
        overlap_end = min(a_end, b_end)
        if overlap_start >= overlap_end:
            return 0.0
        overlap_len = overlap_end - overlap_start
        min_len = min(a_end - a_start, b_end - b_start)
        if min_len <= 0:
            return 0.0
        return overlap_len / min_len

    def get_tracked_signals(self):
        """Return list of currently tracked signals."""
        return list(self._tracked.values())

    def get_status(self):
        """Return detector status dict."""
        return {
            'detection_enabled': self._enabled,
            'tracked_signals': len(self._tracked),
            'total_detections': self._total_detections,
            'threshold_db': self._config.threshold_db,
        }

    def set_param(self, key, value):
        """Update detection parameter."""
        if key == 'threshold_db':
            self._config.threshold_db = float(value)
        elif key == 'min_bandwidth_bins':
            self._config.min_bandwidth_bins = int(value)
        elif key == 'merge_gap_bins':
            self._config.merge_gap_bins = int(value)
        elif key == 'persistence_timeout':
            self._config.persistence_timeout = float(value)
        elif key == 'enabled':
            self.enabled = bool(value)
