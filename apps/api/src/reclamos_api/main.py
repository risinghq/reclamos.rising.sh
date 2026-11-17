from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from reclamos_api.cases.api import router as cases_router
from reclamos_api.config import Settings
from reclamos_api.db import database_pool
from reclamos_api.health import dependency_health
from reclamos_api.ratelimit import RateLimiter, rate_limited
from reclamos_api.retrieval.api import router as search_router
from reclamos_api.retrieval.embedder import Embedder, embedder_from_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_environment()
    async with database_pool(
        settings.database_url, queue_schema=settings.queue_schema
    ) as pool:
        app.state.pool = pool
        app.state.queue_schema = settings.queue_schema
        app.state.embedder = app.state.embedder or embedder_from_settings(settings)
        app.state.min_similarity = settings.refusal_min_similarity
        app.state.rules_min_similarity = settings.rules_min_similarity
        app.state.rules_min_text_rank = settings.rules_min_text_rank
        yield


def create_app(embedder: Embedder | None = None) -> FastAPI:
    """`embedder` replaces the configured model, for tests."""
    settings = Settings.from_environment()
    app = FastAPI(title="Reclamos API", lifespan=lifespan)
    app.state.embedder = embedder
    app.state.rate_limiter = (
        RateLimiter(settings.searches_per_minute)
        if settings.searches_per_minute > 0
        else None
    )
    # The web app calls the API from its own origin. A rewrite through the web
    # host would hide each visitor's address from the API.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.web_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["content-type"],
    )
    for router in (search_router, cases_router):
        app.include_router(router, dependencies=[Depends(rate_limited)])

    @app.get("/health")
    async def health(request: Request) -> JSONResponse:
        payload = await dependency_health(
            request.app.state.pool, queue_schema=request.app.state.queue_schema
        )
        status_code = 200 if payload["status"] == "ok" else 503
        return JSONResponse(status_code=status_code, content=payload)

    return app


app = create_app()
