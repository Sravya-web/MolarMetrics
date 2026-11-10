"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from molarmetrics.analytics.db import connect_readonly
from molarmetrics.config import get_settings
from tests.fixtures.mini_clinic import build_mini_clinic


@pytest.fixture()
def mini_db(tmp_path):
    """Path to a fresh hand-checked mini clinic database."""
    return build_mini_clinic(tmp_path / "mini_clinic.db")


@pytest.fixture()
def mini_conn(mini_db):
    conn = connect_readonly(mini_db)
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def real_db_path():
    """The generated main dataset. Tests using it are skipped if it is missing."""
    path = get_settings().db_path
    if not path.exists():
        pytest.skip("main dataset not generated; run: python -m molarmetrics.data.generate")
    return path
