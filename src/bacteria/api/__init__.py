import uvicorn
from fastapi import FastAPI

from bacteria.api.routes.jobs import router as jobs_router


def create_app() -> FastAPI:
    app = FastAPI(title="Bacteria", version="0.1.0")
    app.include_router(jobs_router)
    return app


def main() -> None:
    uvicorn.run(
        "bacteria.api:create_app",
        factory=True,
        host="0.0.0.0",
        port=8000,
        reload=False,
    )
