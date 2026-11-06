"""Shared pytest config: tests marked `ollama` are skipped unless a server is reachable."""

import os

import httpx
import pytest


def _ollama_up() -> bool:
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    host = host if host.startswith("http") else f"http://{host}"
    try:
        return httpx.get(f"{host.rstrip('/')}/api/version", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


def pytest_collection_modifyitems(config, items):
    marked = [i for i in items if "ollama" in i.keywords]
    if marked and not _ollama_up():
        skip = pytest.mark.skip(reason="Ollama server not reachable (set OLLAMA_HOST or start `ollama serve`)")
        for item in marked:
            item.add_marker(skip)
