"""
Global error handler middleware.
Catches unhandled exceptions and returns user-friendly JSON responses.
"""
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import logging
import traceback

logger = logging.getLogger(__name__)


class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)
            return response
        except Exception as exc:
            logger.error(f"Unhandled error: {request.method} {request.url.path}")
            logger.error(traceback.format_exc())

            status_code = getattr(exc, "status_code", 500)
            detail = getattr(exc, "detail", None)

            if status_code == 500:
                return JSONResponse(
                    status_code=500,
                    content={
                        "detail": "Възникна грешка. Моля опитайте отново.",
                        "error_type": type(exc).__name__,
                        "path": str(request.url.path),
                    },
                )
            return JSONResponse(
                status_code=status_code,
                content={"detail": detail or str(exc)},
            )
