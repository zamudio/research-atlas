"""Same-machine single-owner guard for Semantic Scholar CLI execution."""

import os
import tempfile
from pathlib import Path
from types import TracebackType
from typing import BinaryIO


class SemanticScholarOwnershipError(RuntimeError):
    """Another local Research Atlas process currently owns S2 access."""


class SemanticScholarOwnershipGuard:
    """Hold a non-blocking OS lock for one local S2-enabled execution."""

    def __init__(self, lock_path: Path | None = None) -> None:
        self._lock_path = lock_path or Path(tempfile.gettempdir()) / "research-atlas-s2.lock"
        self._file: BinaryIO | None = None

    def __enter__(self) -> SemanticScholarOwnershipGuard:
        lock_file = self._lock_path.open("a+b")
        try:
            lock_file.seek(0)
            if lock_file.read(1) == b"":
                lock_file.write(b"0")
                lock_file.flush()
            lock_file.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            lock_file.close()
            raise SemanticScholarOwnershipError(
                "another local Research Atlas process currently owns Semantic Scholar access"
            ) from error
        self._file = lock_file
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        if self._file is None:
            return
        lock_file = self._file
        self._file = None
        try:
            if os.name == "nt":
                import msvcrt

                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        finally:
            lock_file.close()
