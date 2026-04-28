import uvicorn
from fastapi import FastAPI

from bacteria.api.routes.jobs import router as jobs_router
from bacteria.observability import setup_observability
from bacteria.observability.tracing import RequestIdMiddleware


def create_app() -> FastAPI:
    app = FastAPI(title="Bacteria", version="0.1.0")

    setup_observability(app=app)

    app.add_middleware(RequestIdMiddleware)

    app.include_router(jobs_router)
    _add_health_routes(app)

    return app


def _add_health_routes(app: FastAPI) -> None:
    from fastapi.responses import JSONResponse
    from sqlalchemy import text

    from bacteria.db import get_engine

    @app.get("/health", tags=["ops"])
    async def health():
        return {"status": "ok"}

    @app.get("/ready", tags=["ops"])
    async def ready():
        try:
            async with get_engine().connect() as conn:
                await conn.execute(text("SELECT 1"))
            return {"status": "ok"}
        except Exception:
            return JSONResponse(status_code=503, content={"status": "unavailable"})


def main() -> None:
    uvicorn.run(
        "bacteria.api:create_app",
        factory=True,
        host="0.0.0.0",
        port=8000,
        reload=False,
    )
