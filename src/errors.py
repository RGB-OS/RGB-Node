from fastapi import Request
from fastapi.responses import JSONResponse
import rgb_lib
import logging

logger = logging.getLogger(__name__)

# Optional: Customize mapping RGB errors to HTTP status codes
RGB_ERROR_STATUS_MAP = {
    "InsufficientBitcoins": 422,
    "InvalidAmountZero": 422,
    "AssetNotFound": 404,
    "FileAlreadyExists": 409,
    "IO": 500,
    "Internal": 500,
    "SyncNeeded": 428,
}

async def rgb_lib_exception_handler(request: Request, exc: rgb_lib.RgbLibError):
    error_type = exc.__class__.__name__
    error_message = str(exc)
    status_code = RGB_ERROR_STATUS_MAP.get(error_type, 400)

    logger.warning(f"[RGB LIB ERROR] {error_type}: {error_message} @ {request.url}")

    return JSONResponse(
        status_code=status_code,
        content={
            "error": error_type,
            "message": error_message,
            "status": status_code,
        },
    )

async def generic_exception_handler(request: Request, exc: Exception):
    logger.error(f"[Unhandled Exception] {type(exc).__name__}: {str(exc)}", exc_info=True)

    return JSONResponse(
        status_code=500,
        content={
            "error": "InternalServerError",
            "message": "[Manager] An unexpected error occurred. Please try again later.",
        },
    )

