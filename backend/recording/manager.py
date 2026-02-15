"""
RecordingManager: coordinates IQ recorder, spectrum recorder,
playback, and file management.

Provides a unified API for the WebSocket handler.
"""

import logging
import json
from pathlib import Path
from typing import List, Dict

from recording.iq_recorder import IQRecorder
from recording.spectrum_recorder import SpectrumRecorder
from recording.playback import IQPlayback

logger = logging.getLogger(__name__)


class RecordingManager:
    """Central coordinator for recording and playback."""

    def __init__(self, config):
        self._config = config
        self._storage_path = Path(config.storage_path)
        self._storage_path.mkdir(parents=True, exist_ok=True)

        self.iq_recorder = IQRecorder(config)
        self.spectrum_recorder = SpectrumRecorder(config)
        self.playback = IQPlayback(config)

    def list_recordings(self) -> List[Dict]:
        """List all recordings in the storage directory, sorted by newest first."""
        recordings = []
        seen = set()

        for meta_file in sorted(
            self._storage_path.glob("*.json"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        ):
            base_name = meta_file.stem
            if base_name in seen:
                continue
            seen.add(base_name)

            try:
                with open(meta_file, 'r') as f:
                    meta = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue

            # Determine type and data file
            if base_name.startswith('iq_'):
                data_file = self._storage_path / f"{base_name}.raw"
                rec_type = 'iq'
            elif base_name.startswith('spectrum_'):
                data_file = self._storage_path / f"{base_name}.csv"
                rec_type = 'spectrum'
            else:
                continue

            size = data_file.stat().st_size if data_file.exists() else 0

            recordings.append({
                'filename': base_name,
                'type': rec_type,
                'size_bytes': size,
                'size_display': self._format_size(size),
                'metadata': meta,
            })

        return recordings

    def delete_recording(self, filename: str) -> bool:
        """Delete a recording and its associated files."""
        # Sanitize
        filename = Path(filename).name
        deleted = False
        for ext in ('.raw', '.csv', '.json', '.sigmf-data', '.sigmf-meta'):
            path = self._storage_path / f"{filename}{ext}"
            if path.exists():
                path.unlink()
                deleted = True

        if deleted:
            logger.info("Deleted recording: %s", filename)
        return deleted

    def get_storage_info(self) -> Dict:
        """Return storage usage statistics."""
        total = 0
        file_count = 0
        try:
            for f in self._storage_path.iterdir():
                if f.is_file():
                    total += f.stat().st_size
                    file_count += 1
        except OSError:
            pass

        return {
            'storage_used': total,
            'storage_used_display': self._format_size(total),
            'storage_limit': self._config.max_storage_bytes,
            'storage_limit_display': self._format_size(
                self._config.max_storage_bytes
            ),
            'storage_percent': (
                total / self._config.max_storage_bytes * 100
                if self._config.max_storage_bytes > 0 else 0
            ),
            'file_count': file_count,
        }

    def get_status(self) -> Dict:
        """Return combined status of all recording/playback components."""
        status = {}
        status.update(self.iq_recorder.get_status())
        status.update(self.spectrum_recorder.get_status())
        status.update(self.playback.get_status())
        status.update(self.get_storage_info())
        return status

    def stop_all(self):
        """Stop all active recordings and playback."""
        self.iq_recorder.stop()
        self.spectrum_recorder.stop()
        self.playback.stop()

    @staticmethod
    def _format_size(bytes_val):
        """Format bytes as human-readable string."""
        for unit in ('B', 'KB', 'MB', 'GB'):
            if bytes_val < 1024:
                return f"{bytes_val:.1f} {unit}"
            bytes_val /= 1024
        return f"{bytes_val:.1f} TB"
