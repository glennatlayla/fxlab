"""
Health service — minimal HTTP server for container health checks.
Demonstrates working FastAPI + logging + graceful shutdown.
"""
import logging
import signal
import sys
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","correlation_id":"%(correlation_id)s","message":"%(message)s"}',
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger(__name__)

# Graceful shutdown flag
shutdown_requested = False


def handle_sigterm(signum, frame):
    """Handle SIGTERM for graceful shutdown."""
    global shutdown_requested
    logger.info("SIGTERM received, initiating graceful shutdown", extra={"correlation_id": "system"})
    shutdown_requested = True


signal.signal(signal.SIGTERM, handle_sigterm)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan manager."""
    logger.info("Health service starting", extra={"correlation_id": "system"})
    yield
    logger.info("Health service shutting down", extra={"correlation_id": "system"})


app = FastAPI(title="FXLab Health Service", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    """Extract or generate correlation ID for every request."""
    correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    
    # Log request
    logger.info(
        f"Request: {request.method} {request.url.path}",
        extra={"correlation_id": correlation_id}
    )
    
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = correlation_id
    
    # Log response
    logger.info(
        f"Response: {response.status_code}",
        extra={"correlation_id": correlation_id}
    )
    
    return response


@app.get("/health")
async def health_check():
    """
    Basic health check — always returns 200 if service is running.
    
    This endpoint is used by container orchestrators to determine if
    the service should receive traffic.
    """
    return JSONResponse(
        status_code=200,
        content={
            "status": "healthy",
            "service": "health",
            "version": "0.1.0",
        },
    )


@app.get("/ready")
async def readiness_check():
    """
    Readiness check — returns 503 if shutdown requested.
    
    This endpoint signals when the service should be removed from
    load balancer rotation during graceful shutdown.
    """
    if shutdown_requested:
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "reason": "shutdown_in_progress",
            },
        )
    return JSONResponse(
        status_code=200,
        content={
            "status": "ready",
            "service": "health",
        },
    )


@app.get("/live")
async def liveness_check():
    """
    Liveness check — returns 200 if process is alive.
    
    This endpoint is used by container orchestrators to determine if
    the container should be restarted.
    """
    return JSONResponse(
        status_code=200,
        content={
            "status": "alive",
            "service": "health",
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_config=None,  # Use our structured logging
    )
