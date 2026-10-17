"""Scaffold smoke tests: package import, network guard, gitignore rules."""

import socket
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_import_package_without_env_does_not_read_env_or_network():
    import buyer_agent

    assert buyer_agent.__doc__


def test_network_guard_blocks_socket_connect():
    with pytest.raises(RuntimeError, match="network access blocked"):
        socket.socket().connect(("127.0.0.1", 9))


def test_gitignore_has_runs_data_venv():
    lines = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    for entry in (".venv/", "runs/", "/data/"):
        assert entry in lines
