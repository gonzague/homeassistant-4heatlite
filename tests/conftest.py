"""Offline regression tests: no test may connect to a real stove."""
import socket

import homeassistant  # Set up HA's validation compatibility before integration imports.
import pytest


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Tests must not connect to a real device")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
