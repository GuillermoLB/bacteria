"""Scaffold smoke tests — verifies the module structure is importable."""
import importlib

import pytest


MODULES = [
    "bacteria",
    "bacteria.settings",
    "bacteria.dependencies",
    "bacteria.api",
    "bacteria.worker",
    "bacteria.scheduler",
    "bacteria.queue",
    "bacteria.workflows",
    "bacteria.nodes",
    "bacteria.agents",
    "bacteria.tools",
    "bacteria.skills",
    "bacteria.memory",
    "bacteria.context",
    "bacteria.entities",
    "bacteria.db",
    "bacteria.observability",
    "bacteria.utils",
]


@pytest.mark.parametrize("module", MODULES)
def test_module_is_importable(module: str) -> None:
    importlib.import_module(module)


def test_get_settings_returns_same_instance() -> None:
    from bacteria.settings import get_settings

    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2


def test_postgres_url_format() -> None:
    from bacteria.settings import PostgresSettings

    s = PostgresSettings(host="myhost", port=5432, user="u", password="p", db="d")
    assert s.url == "postgresql+psycopg://u:p@myhost:5432/d"
