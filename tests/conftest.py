"""
Pytest configuration and shared fixtures for scraper_backend tests.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

import app.database as db_module
from app.database import init_db
from app.main import app

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def load_fixture():
    """Helper to read contents of fixture files."""
    def _loader(filename: str) -> str:
        path = FIXTURES_DIR / filename
        if not path.exists():
            raise FileNotFoundError(f"Fixture {filename} not found in {FIXTURES_DIR}")
        return path.read_text(encoding="utf-8")
    return _loader


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    """Point DB_PATH to a temporary sqlite db for every test."""
    test_db_path = str(tmp_path / "test_data.db")
    monkeypatch.setattr(db_module, "DB_PATH", test_db_path)
    asyncio.run(init_db())
    yield test_db_path


@pytest.fixture
def client():
    """FastAPI test client."""
    with TestClient(app) as test_client:
        yield test_client
