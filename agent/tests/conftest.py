"""Tests must not load personal credentials or contact model/MCP services."""
import os
import socket
import sys
import urllib.request

os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["AGENT_MODEL"] = "gemini-3.5-flash"

import aiohttp
import httpx
import pytest


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Offline test attempted a network request")

    original_connect = socket.socket.connect
    socketpair_code = getattr(socket.socketpair, "__code__", None)

    def guarded_connect(sock, address):
        if socketpair_code is not None and sys._getframe(1).f_code is socketpair_code:
            return original_connect(sock, address)
        return blocked()

    # Blocking HTTP transports catches Gemini, LiteLLM and MCP, while leaving
    # Windows asyncio's internal socketpair available to create an event loop.
    monkeypatch.setattr(httpx.Client, "send", blocked)
    monkeypatch.setattr(httpx.AsyncClient, "send", blocked)
    monkeypatch.setattr(aiohttp.ClientSession, "_request", blocked)
    monkeypatch.setattr(urllib.request, "urlopen", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
