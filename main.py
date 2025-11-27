from dotenv import load_dotenv
from fastapi.responses import JSONResponse
load_dotenv(override=True)
from src.errors import generic_exception_handler, rgb_lib_exception_handler
from src.wallet_utils import WalletNotFoundError
from fastapi import FastAPI,Request
from src.routes import router 
import rgb_lib
import os
import logging

logger = logging.getLogger(__name__)

app = FastAPI(title="ThunderLink RGB Wallet API",
    version="1.0.0",
    description="API documentation for RGB wallet management and asset transfers")
app.add_exception_handler(rgb_lib.RgbLibError, rgb_lib_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)
@app.exception_handler(WalletNotFoundError)
async def wallet_not_found_handler(request: Request, exc: WalletNotFoundError):
    return JSONResponse(
        status_code=404,
        content={"error": str(exc)}
    )

@app.on_event("startup")
async def startup_event():
    """Initialize database and recover active watchers on startup."""
    try:
        from src.queue import init_database, recover_active_watchers
        
        # Initialize database schema
        logger.info("Initializing database schema...")
        init_database()
        logger.info("Database schema initialized")
        
        # Recover active watchers if enabled
        if os.getenv("ENABLE_RECOVERY", "true").lower() == "true":
            logger.info("Recovering active watchers...")
            recovered = recover_active_watchers()
            logger.info(f"Recovery complete: {recovered} watchers recovered")
        else:
            logger.info("Recovery disabled (ENABLE_RECOVERY=false)")
    except Exception as e:
        logger.error(f"Startup error: {e}", exc_info=True)
        # Don't fail startup if recovery fails, but log it

app.include_router(router)