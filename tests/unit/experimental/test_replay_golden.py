"""Pinned golden bytes for the existing V1 producer, independent of replay output."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tests.unit.experimental.test_replay_integrity import _write_producer_pair


GOLDENS = {
    "empty": (
        "eafb49970bc03f7769b4dec275c5f38dcae320f1228c19b3d446f08872fcdb5a",
        "adff72d4ccef33c85a543602839a91933f3389c1b3d79000cb4f642f33790da9",
    ),
    "unicode": (
        "bf6fa1093ba1e13be0cf79296a5aa3aaa14dec812a65e2a9636910e6d8497c8e",
        "23fb2d682f21777272e6a17c4ba24e4a60e3b24f64e2e7d637f2004c3379151f",
    ),
}


@pytest.mark.parametrize("variant", ["empty", "unicode"])
def test_existing_v1_output_matches_reviewed_golden_sha256(variant: str, tmp_path: Path) -> None:
    _, _, json_bytes, csv_bytes = _write_producer_pair(tmp_path, include_unicode=(variant == "unicode"))
    assert (hashlib.sha256(json_bytes).hexdigest(), hashlib.sha256(csv_bytes).hexdigest()) == GOLDENS[variant]
