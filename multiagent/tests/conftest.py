"""Shared fixtures. Blocks real network connects unless a test is marked `live`."""

import socket

import pytest


@pytest.fixture(autouse=True)
def _block_network(request, monkeypatch):
    if request.node.get_closest_marker("live"):
        return

    def _blocked(self, *args, **kwargs):
        raise RuntimeError("network access blocked in tests; mark the test `live` to allow it")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
