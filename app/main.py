"""Main FastAPI application"""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from app.config import settings
from app.models.base import init_db
from app.api import instances, project_pairs, user_mappings, sync, dashboard
from app.scheduler import scheduler

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
