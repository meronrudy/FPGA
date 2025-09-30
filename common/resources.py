# common/resources.py
"""
Cross-process file-based resource locking with TTL and stale-lock recovery.

Usage:
    from common.resources import FileLock, LockError

    try:
        with FileLock("icebreaker", ttl=180, poll_interval=0.5) as lock:
            # exclusive access to the iCEBreaker board
            flash_bitstream(...)
    except LockError as e:
        # handle contention/timeout

Design:
- Lock file lives under artifacts/locks/<name>.lock by default.
- Acquisition uses O_CREAT|O_EXCL for atomic creation on POSIX.
- Reentrant in-process: if the same PID holds the lock file, acquisition succeeds.
- TTL-based stale recovery: if the lock file is older than ttl seconds, it is removed.
- Safe release: only the owning PID removes the lock; missing-file on release is tolerated.

This module is intentionally self-contained and has no external dependencies.
"""

from __future__ import annotations

import errno
import json
import os
import time
from pathlib import Path
from typing import Optional


class LockError(Exception):
    """Raised when a lock cannot be acquired or maintained."""


def _safe_name(name: str) -> str:
    """
    Sanitize a lock name to file-system-safe characters.
    """
    cleaned = "".join(ch if (ch.isalnum() or ch in "-_.") else "_" for ch in name.strip())
    return cleaned or "lock"


class FileLock:
    """
    File-based lock with TTL and reentrant behavior for the same PID.

    Parameters:
        name: Logical resource name (e.g., "icebreaker").
        dir: Directory to store lock files (default: artifacts/locks).
        ttl: Time-to-live in seconds for considering a lock stale (default: 180).
        poll_interval: Seconds between acquisition retries (default: 0.5).
        timeout: Optional maximum time to wait for acquisition; None means wait forever.
        reentrant: Allow the same PID to treat an existing lock file as acquired (default: True).
    """

    def __init__(
        self,
        name: str,
        *,
        dir: Path | str = Path("artifacts") / "locks",
        ttl: int = 180,
        poll_interval: float = 0.5,
        timeout: Optional[float] = None,
        reentrant: bool = True,
    ) -> None:
        self.dir = Path(dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / f"{_safe_name(name)}.lock"
        self.ttl = max(1, int(ttl))
        self.poll_interval = max(0.05, float(poll_interval))
        self.timeout = timeout
        self.reentrant = reentrant
        self._pid = os.getpid()
        self._owned = False

    def __enter__(self) -> "FileLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()

    # Public API

    def acquire(self) -> None:
        """
        Acquire the lock, waiting up to self.timeout if provided.

        Raises:
            LockError if the lock cannot be acquired within timeout.
        """
        start = time.time()
        while True:
            if self._try_create():
                self._owned = True
                return

            # If lock exists, check reentrancy/staleness
            if self.path.exists():
                if self.reentrant and self._is_owned_by_me():
                    # already owned by this PID
                    self._owned = True
                    return

                if self._is_stale():
                    # stale lock: remove and retry immediately
                    try:
                        self.path.unlink()
                    except FileNotFoundError:
                        pass
                    except OSError as e:
                        # Could not remove; fall through to wait
                        if e.errno != errno.ENOENT:
                            time.sleep(self.poll_interval)
                    continue

            # Check timeout
            if self.timeout is not None:
                elapsed = time.time() - start
                if elapsed >= self.timeout:
                    raise LockError(f"Timeout acquiring lock: {self.path}")

            time.sleep(self.poll_interval)

    def release(self) -> None:
        """
        Release the lock if owned by this process. Ignores missing file.
        """
        if not self._owned:
            return
        # Only remove if the file still claims our PID
        if self._is_owned_by_me():
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
        self._owned = False

    # Internals

    def _try_create(self) -> bool:
        """
        Attempt to atomically create the lock file for exclusive ownership.
        Returns True on success.
        """
        now = time.time()
        payload = {
            "pid": self._pid,
            "created": now,
            "updated": now,
        }
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        try:
            fd = os.open(self.path, flags, 0o644)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(payload, fh)
                    fh.flush()
                    os.fsync(fh.fileno())
            finally:
                # fd will be closed by fdopen context
                pass
            return True
        except FileExistsError:
            return False
        except OSError as e:
            # If file exists, treat as contention; otherwise surface error
            if e.errno == errno.EEXIST:
                return False
            raise

    def _read_meta(self) -> Optional[dict]:
        try:
            text = self.path.read_text(encoding="utf-8")
            return json.loads(text)
        except Exception:
            return None

    def _is_owned_by_me(self) -> bool:
        meta = self._read_meta()
        return bool(meta) and int(meta.get("pid", -1)) == self._pid

    def _is_stale(self) -> bool:
        try:
            mtime = self.path.stat().st_mtime
        except FileNotFoundError:
            return False
        age = time.time() - mtime
        return age > self.ttl

    def touch(self) -> None:
        """
        Refresh the lock's 'updated' timestamp, useful for long operations.
        No-op if not owned.
        """
        if not self._owned:
            return
        try:
            meta = self._read_meta() or {}
            meta["pid"] = self._pid
            meta["updated"] = time.time()
            self.path.write_text(json.dumps(meta), encoding="utf-8")
        except Exception:
            # Keep silent; the lock is still valid as long as file exists.
            pass