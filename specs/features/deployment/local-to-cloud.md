# Feature: Local-to-Cloud Deployment

**Status**: Implemented
**Owner**: GuillermoLB
**Last Updated**: 2026-04-24

## Purpose

Make bacteria runnable locally as a full stack with a single command, and deployable to a cloud VPS via a single `git push`. Local dev and production use the same Docker image — different config, not different code.

## Guiding principle

From the reference: *"I don't need microservices right now. I just want a simple system where I understand all the individual building blocks."*

One VPS. One Docker Compose file. One CI/CD pipeline. No ECS, no Kubernetes, no EFS. That complexity is a future concern if usage outgrows a single instance.

## Scope

This spec covers the local dev stack and CI/CD pipeline. Reverse proxy and HTTPS (Caddy) are deferred to a separate cloud deployment spec — they are only needed when the server is exposed to the public internet.

## Target developer experience

```bash
# Local dev — start everything
docker-compose up

# Ship to production
git push origin main   # CI/CD auto-deploys
```

## Architecture

```
VPS (single server)
├── bacteria-api (uvicorn, port 8000)
├── bacteria-worker (polling worker)
└── Postgres 16

All managed by Docker Compose.
context/memory/ lives on the server filesystem — same as local.
```

## What needs to be built

### 1. `Dockerfile`

Single image, all three entry points. The `command` override in Docker Compose selects which process runs.

Follows uv Docker best practices (see `references/uv-docker-github.md`): binary copy, layer caching, lockfile install, bytecode compilation.

```dockerfile
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /uvx /bin/

WORKDIR /app

# Install dependencies first — cached until uv.lock or pyproject.toml changes
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

# Copy source and install the project with bytecode compilation
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --compile-bytecode

ENV PATH="/app/.venv/bin:$PATH"

CMD ["bacteria-api"]
```

### 2. `.dockerignore`

Prevents `.venv` and secrets from leaking into the image:

```
.venv
__pycache__
*.pyc
.env
context/memory
```

`context/memory` is excluded from the image — it is mounted as a volume at runtime.

### 3. `docker-compose.yml` — extend for full local stack

Add `api` and `worker` services to the existing Postgres-only compose file:

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: bacteria
      POSTGRES_PASSWORD: bacteria
      POSTGRES_DB: bacteria
    ports:
      - "5433:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U bacteria"]
      interval: 5s
      timeout: 5s
      retries: 5

  api:
    build: .
    command: bacteria-api
    env_file: .env
    ports:
      - "8000:8000"
    volumes:
      - ./context:/app/context
    depends_on:
      postgres:
        condition: service_healthy

  worker:
    build: .
    command: bacteria-worker
    env_file: .env
    volumes:
      - ./context:/app/context
    depends_on:
      postgres:
        condition: service_healthy

volumes:
  postgres_data:
```

The `./context` volume mount means:
- Locally: `context/memory/` on the host filesystem
- On the VPS: same path on the server's disk
- `soul.md`, memory files, skills — all shared between API and worker containers

### 4. `docker-compose.prod.yml` — production overrides

Thin override file for production — restart policies, no exposed Postgres port:

```yaml
services:
  api:
    restart: unless-stopped

  worker:
    restart: unless-stopped

  postgres:
    ports: []
```

Run in production with:
```bash
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### 5. `.env.example`

Documents all required env vars. Developers copy to `.env` locally; the VPS has a real `.env` with production values.

```bash
# Postgres
POSTGRES__HOST=postgres
POSTGRES__PORT=5432
POSTGRES__USER=bacteria
POSTGRES__PASSWORD=changeme
POSTGRES__DB=bacteria

# Worker
WORKER__CONCURRENCY=5
WORKER__POLL_INTERVAL=5
WORKER__STUCK_THRESHOLD=600

# Agent
AGENT__MODEL=claude-sonnet-4-6
AGENT__MAX_TURNS=20
AGENT__MAX_COST=1.0

# WhatsApp
WHATSAPP__WEBHOOK_SECRET=changeme

# Observability (optional)
LOG_LEVEL=INFO
```

### 6. GitHub Actions CI/CD

On push to `main`: checkout, setup uv with cache, SSH into VPS and redeploy.

Uses `astral-sh/setup-uv` with cache enabled — keyed on `uv.lock` so dependency downloads are skipped on most runs.

```yaml
# .github/workflows/deploy.yml
name: Deploy

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: astral-sh/setup-uv@v7
        with:
          version: "0.11.7"
          enable-cache: true

      - name: Deploy to VPS
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.VPS_HOST }}
          username: ${{ secrets.VPS_USER }}
          key: ${{ secrets.VPS_SSH_KEY }}
          script: |
            cd /srv/bacteria
            git pull origin main
            docker-compose -f docker-compose.yml -f docker-compose.prod.yml build
            docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

GitHub secrets needed: `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`.

### 7. `GET /health` endpoint

Required for monitoring:

```python
@router.get("/health")
async def health():
    return {"status": "ok"}
```

### 8. Database migrations on deploy

The CI/CD script applies migrations before restarting services:

```bash
docker-compose run --rm api \
  psql $DATABASE_URL -f scripts/migrations/0001_create_jobs.sql
```

## What does NOT change

- All source code — zero changes
- `context/memory/` — stays as files, mounted as a volume
- Settings — already env-var driven via pydantic-settings
- The three entry points — `bacteria-api`, `bacteria-worker`, `bacteria-chat`

## File structure after this spec

```
bacteria/
├── Dockerfile
├── .dockerignore
├── docker-compose.yml           # extended — includes api + worker
├── docker-compose.prod.yml      # production overrides
├── .env.example
└── .github/
    └── workflows/
        └── deploy.yml
```

## Acceptance Criteria

- [ ] `Dockerfile` builds successfully — `docker build .`
- [ ] `.dockerignore` excludes `.venv`, `__pycache__`, `.env`, `context/memory`
- [ ] uv version pinned in `Dockerfile` (`COPY --from=ghcr.io/astral-sh/uv:0.11.7`)
- [ ] Dependency layer cached separately from source layer
- [ ] `docker-compose up` starts Postgres + API + worker locally
- [ ] API responds at `http://localhost:8000/health`
- [ ] Worker claims and processes jobs when running via Docker Compose
- [ ] `context/memory/` is shared between API and worker containers via volume mount
- [ ] `docker-compose.prod.yml` exists with restart policies and no exposed Postgres port
- [ ] `.env.example` documents all required env vars
- [ ] GitHub Actions workflow uses `astral-sh/setup-uv@v7` with `enable-cache: true`
- [ ] GitHub Actions workflow deploys on push to `main`
- [ ] Deploy script runs migrations before restarting services

## Dependencies

- `specs/features/api/api.md` — health endpoint addition
- `specs/features/scaffold/project-scaffold.md` — Implemented
- `references/uv-docker-github.md` — uv Docker and GitHub Actions patterns
