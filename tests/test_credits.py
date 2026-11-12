# Copyright (c) 2026 Shashikanth Dhanekula
# SPDX-License-Identifier: MIT
"""Mandatory author signature / credits checks."""

from __future__ import annotations

from pathlib import Path

import pytest

from dgx_lab import AUTHOR, COPYRIGHT, SPDX_LICENSE, credits
from dgx_lab.cli import main

REPO_ROOT = Path(__file__).resolve().parents[1]
SIGNATURE = "Shashikanth Dhanekula"
SPDX = "SPDX-License-Identifier: MIT"

FIRST_PARTY_GLOBS = (
    "src/dgx_lab/*.py",
    "tests/test_*.py",
    "scripts/phase1",
)


def _first_party_files() -> list[Path]:
    files: list[Path] = []
    for pattern in FIRST_PARTY_GLOBS:
        files.extend(sorted(REPO_ROOT.glob(pattern)))
    # Exclude caches / bytecode
    return [p for p in files if p.is_file() and "__pycache__" not in p.parts]


def test_credits_string():
    text = credits()
    assert AUTHOR in text
    assert COPYRIGHT in text
    assert SPDX_LICENSE in text
    assert SIGNATURE in text


def test_cli_credits(capsys):
    assert main(["credits"]) == 0
    out = capsys.readouterr().out
    assert SIGNATURE in out
    assert "SPDX-License-Identifier: MIT" in out or "License: MIT" in out


@pytest.mark.parametrize("path", _first_party_files(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_first_party_files_carry_signature(path: Path):
    text = path.read_text(encoding="utf-8")
    assert SIGNATURE in text, f"{path} missing author signature"
    assert SPDX in text, f"{path} missing SPDX header"
