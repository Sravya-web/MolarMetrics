"""Retention: how long uploaded data stays on this computer.

The rule (one clock for everything uploaded):

* An uploaded dataset is deleted when it has not been used for
  ``MOLARMETRICS_RETENTION_HOURS`` (default 24). Every request that reads a
  dataset refreshes its "last used" time.
* Unfinished uploads (files waiting on the review screen) follow the same rule.
* Checks happen at server start (deleting ONLY what has expired), every
  ``MOLARMETRICS_CLEANUP_INTERVAL_MINUTES`` while running, and whenever an
  expired dataset is requested (so nothing is served between sweeps).
* "Remove dataset" deletes immediately and verifies the files are gone.

The bundled sample database is never deleted: a sample entry only points at
it. Deletion is ordinary file deletion, not a secure erase. Logs name dataset
IDs and counts only, never names or contents.
"""

from __future__ import annotations

import logging
import shutil
import time
from collections.abc import Callable
from pathlib import Path

from molarmetrics.api.settings import WebSettings
from molarmetrics.api.store import BatchRow, DatasetRow, Store

log = logging.getLogger("molarmetrics.retention")


class DeletionFailed(RuntimeError):
    pass


class Retention:
    def __init__(self, store: Store, settings: WebSettings,
                 on_dataset_removed: Callable[[str], None] | None = None):
        self.store = store
        self.settings = settings
        self.on_dataset_removed = on_dataset_removed

    def expired(self, last_used_at: float, now: float | None = None) -> bool:
        return (now or time.time()) - last_used_at > self.settings.retention_seconds

    def expires_at(self, last_used_at: float) -> float:
        return last_used_at + self.settings.retention_seconds

    # --- deleting -----------------------------------------------------------------------
    def _delete_folder(self, folder: Path, root: Path) -> None:
        """Delete a folder that must sit directly inside ``root``, then verify."""
        folder, root = folder.resolve(), root.resolve()
        if folder.parent != root:
            raise DeletionFailed("refusing to delete a folder outside the runtime directory")
        if folder.exists():
            shutil.rmtree(folder, ignore_errors=True)
        if folder.exists():
            raise DeletionFailed("folder still exists after deletion")

    def remove_dataset(self, row: DatasetRow) -> None:
        """Delete an uploaded dataset's files (verified), then its registry row.
        A sample entry only loses its registry row."""
        if row.kind == "uploaded":
            self._delete_folder(Path(row.db_path).parent, self.settings.datasets_dir)
        self.store.delete_dataset(row.id)
        if self.on_dataset_removed:
            self.on_dataset_removed(row.id)
        log.info("Removed dataset %s (%s)", row.id, row.kind)

    def remove_batch(self, batch: BatchRow) -> None:
        self._delete_folder(self.settings.staging_dir / batch.id, self.settings.staging_dir)
        self.store.delete_batch(batch.id)

    # --- sweeping -------------------------------------------------------------------------
    def sweep(self, now: float | None = None, startup: bool = False) -> dict[str, int]:
        """Delete what has expired. Never deletes unexpired uploads."""
        now = now or time.time()
        cutoff = now - self.settings.retention_seconds
        removed = {"datasets": 0, "uploads_in_review": 0, "sessions": 0, "leftover_folders": 0}
        for row in self.store.all_datasets():
            if row.kind == "uploaded" and row.last_used_at < cutoff:
                if self._try(self.remove_dataset, row):
                    removed["datasets"] += 1
        for batch in self.store.all_batches():
            if batch.last_used_at < cutoff:
                if self._try(self.remove_batch, batch):
                    removed["uploads_in_review"] += 1
        for session_id in self.store.sessions_idle_since(cutoff):
            for row in self.store.list_datasets(session_id):
                self._try(self.remove_dataset, row)
            self.store.delete_session(session_id)
            removed["sessions"] += 1
        removed["leftover_folders"] = self._leftovers(cutoff, startup)
        if any(removed.values()):
            log.info("Retention sweep removed: %s", removed)
        return removed

    def _leftovers(self, cutoff: float, startup: bool) -> int:
        """Folders the registry no longer knows about. Incomplete imports
        (``.<id>.tmp``) are removed at startup (no import can be running then);
        other unknown folders only once they are older than the retention window."""
        count = 0
        known_datasets = {Path(r.db_path).parent.name for r in self.store.all_datasets() if r.kind == "uploaded"}
        known_batches = {b.id for b in self.store.all_batches()}
        for root, known in ((self.settings.datasets_dir, known_datasets), (self.settings.staging_dir, known_batches)):
            if not root.exists():
                continue
            for child in root.iterdir():
                if not child.is_dir() or child.name in known:
                    continue
                incomplete = child.name.startswith(".") and child.name.endswith(".tmp")
                if (incomplete and startup) or child.stat().st_mtime < cutoff:
                    if self._try(self._delete_folder, child, root):
                        count += 1
        return count

    @staticmethod
    def _try(fn, *args) -> bool:
        try:
            fn(*args)
            return True
        except Exception as exc:  # keep sweeping; the item is retried next time
            log.warning("Retention could not remove an item (%s)", type(exc).__name__)
            return False
