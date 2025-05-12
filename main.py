from dotenv import load_dotenv
from fastapi.responses import JSONResponse
load_dotenv()
from src.errors import generic_exception_handler, rgb_lib_exception_handler
from src.wallet_utils import WalletNotFoundError
from fastapi import FastAPI,Request
from src.routes import router 
from rgb_lib import rgb_lib



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
app.include_router(router)