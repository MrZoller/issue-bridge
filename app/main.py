"""Main FastAPI application"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from app.api import dashboard, instances, project_pairs, sync, user_mappings
from app.config import settings
from app.models.base import init_db
from app.scheduler import scheduler
from app.security import BasicAuthMiddleware

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    # Startup
    logger.info("Starting GitLab Issue Sync Service")
    init_db()
    scheduler.start()
    yield
    # Shutdown
    logger.info("Stopping GitLab Issue Sync Service")
    scheduler.stop()


app = FastAPI(
    title="GitLab Issue Sync Service",
    description="Synchronize issues between GitLab instances",
    version="1.0.0",
    lifespan=lifespan,
)

# Optional built-in auth (recommended if exposed beyond localhost/private networks)
if settings.auth_enabled:
    if not settings.auth_username or not settings.auth_password:
        raise RuntimeError("AUTH_ENABLED=true requires AUTH_USERNAME and AUTH_PASSWORD to be set")
    app.add_middleware(
        BasicAuthMiddleware,
        username=settings.auth_username,
        password=settings.auth_password,
        allow_paths={"/health"},
    )

# Include API routers
app.include_router(instances.router)
app.include_router(project_pairs.router)
app.include_router(user_mappings.router)
app.include_router(sync.router)
app.include_router(dashboard.router)

# Mount static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Templates
templates = Jinja2Templates(directory="app/templates")


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Serve the main dashboard page"""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "GitLab Issue Sync"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level=settings.log_level.lower(),
    )
