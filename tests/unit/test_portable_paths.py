"""Todo arquivo rastreado precisa fazer checkout no Windows (NTFS), senão a CI nem chega aos testes."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
INVALID_CHARS = re.compile(r'[<>:"|?*\\\x00-\x1f]')
RESERVED = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?$", re.IGNORECASE)


def _tracked_files():
    if shutil.which("git") is None or not (REPO / ".git").exists():
        pytest.skip("sem checkout git")
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO, capture_output=True, check=True
    ).stdout.decode("utf-8")
    return [p for p in out.split("\0") if p]


def test_tracked_paths_are_valid_on_windows():
    bad = []
    for path in _tracked_files():
        for part in path.split("/"):
            if INVALID_CHARS.search(part) or part.endswith((".", " ")) or RESERVED.match(part):
                bad.append(path)
                break
    assert not bad, f"caminhos inválidos no Windows: {bad}"
