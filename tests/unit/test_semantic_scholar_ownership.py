import sys
from pathlib import Path
from subprocess import PIPE, Popen

import pytest

from research_atlas.infrastructure.providers.semantic_scholar_ownership import (
    SemanticScholarOwnershipError,
    SemanticScholarOwnershipGuard,
)


def test_single_owner_guard_rejects_concurrent_owner_and_allows_reacquisition(
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / "s2.lock"

    with SemanticScholarOwnershipGuard(lock_path):
        with pytest.raises(SemanticScholarOwnershipError, match="another local Research Atlas"):
            with SemanticScholarOwnershipGuard(lock_path):
                raise AssertionError("second owner must not enter")

    with SemanticScholarOwnershipGuard(lock_path):
        pass


def test_single_owner_guard_releases_after_exception(tmp_path: Path) -> None:
    lock_path = tmp_path / "s2.lock"

    with pytest.raises(RuntimeError, match="body failed"):
        with SemanticScholarOwnershipGuard(lock_path):
            raise RuntimeError("body failed")

    with SemanticScholarOwnershipGuard(lock_path):
        pass


def test_single_owner_guard_excludes_a_second_os_process(tmp_path: Path) -> None:
    lock_path = tmp_path / "cross-process.lock"
    child_code = """
import sys
from pathlib import Path
from research_atlas.infrastructure.providers.semantic_scholar_ownership import (
    SemanticScholarOwnershipGuard,
)
with SemanticScholarOwnershipGuard(Path(sys.argv[1])):
    print("ready", flush=True)
    sys.stdin.readline()
"""
    child = Popen(
        [sys.executable, "-c", child_code, str(lock_path)],
        stdin=PIPE,
        stdout=PIPE,
        stderr=PIPE,
        text=True,
    )
    assert child.stdin is not None
    assert child.stdout is not None
    try:
        assert child.stdout.readline().strip() == "ready"
        with pytest.raises(SemanticScholarOwnershipError):
            with SemanticScholarOwnershipGuard(lock_path):
                raise AssertionError("second process must not acquire the guard")
    finally:
        child.stdin.write("release\n")
        child.stdin.flush()
        _, stderr = child.communicate(timeout=10)
        assert child.returncode == 0, stderr

    with SemanticScholarOwnershipGuard(lock_path):
        pass
