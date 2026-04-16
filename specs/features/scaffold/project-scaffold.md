# Feature: Project Scaffold

**Status**: Draft
**Owner**: GuillermoLB
**Last Updated**: 2026-04-12
**Priority**: High

## Purpose

Establish the full `src/bacteria/` module structure so every future feature has a clear, agreed-upon home. This is not functional code — it is the skeleton that makes the architecture navigable and prevents modules from ending up in the wrong place.

## Requirements

- [ ] All modules listed in `specs/architecture/architecture.md` exist as Python packages (directories with `__init__.py`)
- [ ] `pyproject.toml` is correctly configured: package name, version, `requires-python`, entry point
- [ ] A `settings.py` exists in `src/bacteria/` with nested Pydantic Settings groups (one per subsystem), using `get_settings()` + `@lru_cache`
- [ ] A `dependencies.py` exists at `src/bacteria/` — empty composition root, ready to be filled
- [ ] `tests/` mirrors the `src/bacteria/` structure with one placeholder test file
- [ ] The project runs `uv run python -c "import bacteria"` without errors

## Structure

```
bacteria/
├── pyproject.toml
├── .env.example               # Documents all required env vars, no real values
├── tests/
│   └── __init__.py
└── src/
    └── bacteria/
        ├── __init__.py
        ├── settings.py        # Pydantic Settings — get_settings() + @lru_cache
        ├── dependencies.py    # Composition root — empty, wired incrementally
        ├── api/
        │   └── __init__.py
        ├── worker/
        │   └── __init__.py
        ├── scheduler/
        │   └── __init__.py
        ├── queue/
        │   └── __init__.py
        ├── workflows/
        │   └── __init__.py
        ├── nodes/
        │   └── __init__.py
        ├── agents/
        │   └── __init__.py
        ├── tools/
        │   └── __init__.py
        ├── skills/
        │   └── __init__.py
        ├── memory/
        │   └── __init__.py
        ├── context/
        │   └── __init__.py
        ├── entities/
        │   └── __init__.py
        ├── db/
        │   └── __init__.py
        ├── observability/
        │   └── __init__.py
        └── utils/
            └── __init__.py
```

## `settings.py` shape

Nested Pydantic Settings with one group per subsystem. Each group reads from its own env prefix.

```python
from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class PostgresSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="POSTGRES__", env_file=".env", extra="ignore")
    host: str = "localhost"
    port: int = 5432
    user: str = "bacteria"
    password: str = "bacteria"
    db: str = "bacteria"

    @property
    def url(self) -> str:
        return f"postgresql+psycopg://{self.user}:{self.password}@{self.host}:{self.port}/{self.db}"

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    log_level: str = "INFO"
    postgres: PostgresSettings = Field(default_factory=PostgresSettings)
    # llms, agents, api groups added when those modules are built

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
```

## `.env.example` shape

Documents every env var the system will need. No real values — only names and descriptions.

```
# PostgreSQL
POSTGRES__HOST=localhost
POSTGRES__PORT=5432
POSTGRES__USER=bacteria
POSTGRES__PASSWORD=
POSTGRES__DB=bacteria
```

## Acceptance Criteria

### Scenario 1: Package imports cleanly

```
Given the scaffold is created
When running: uv run python -c "import bacteria"
Then no ImportError is raised
```

### Scenario 2: All modules are importable

```
Given the scaffold is created
When importing any module: from bacteria import api, worker, queue, entities, db
Then all imports succeed without error
```

### Scenario 3: Settings loads from environment

```
Given a .env file with POSTGRES__HOST=myhost
When calling get_settings()
Then settings.postgres.host == "myhost"
And calling get_settings() twice returns the same object (lru_cache)
```

### Scenario 4: No circular imports

```
Given the scaffold is created
When running: uv run python -m pytest --collect-only
Then no circular import errors appear
```

## Technical Notes

- `__init__.py` files are empty — no re-exports at this stage
- `dependencies.py` is empty except for a module docstring explaining its role
- `settings.py` only includes `PostgresSettings` for now — other groups added per feature
- Use `psycopg` (v3) driver, not `psycopg2`
- `pydantic-settings` must be added to `pyproject.toml` dependencies

## Dependencies

- [ ] **pydantic-settings**: Required for `Settings` classes
- [ ] **psycopg**: Required for the Postgres URL driver prefix (added here, used in `db/`)

## Implementation

> Fill in after implementation.

- **Source**: `src/bacteria/`
- **Tests**: `tests/`

---

**Status History**: Draft (2026-04-12)
