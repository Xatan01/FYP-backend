import asyncio
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes import auth
from routes import inference
from routes import lesson
from routes import market
from routes import quiz
from routes import trading_journal
from routes import virtual_market
from services.model_inference import validate_model_env
from services.vm_scheduler import run_daily_price_sync_forever
from dotenv import load_dotenv

# psycopg async is incompatible with Windows ProactorEventLoop.
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/auth")
app.include_router(lesson.router, prefix="/lesson", tags=["lesson"])
app.include_router(quiz.router, prefix="/quiz", tags=["quiz"])
app.include_router(market.router, prefix="/market")
app.include_router(virtual_market.router, prefix="/virtual-market")
app.include_router(trading_journal.router, prefix="/trading-journal")
app.include_router(inference.router)


@app.on_event("startup")
def startup_checks():
    validate_model_env()


@app.on_event("startup")
async def start_virtual_market_scheduler():
    app.state.vm_scheduler_task = asyncio.create_task(run_daily_price_sync_forever())


@app.on_event("shutdown")
async def stop_virtual_market_scheduler():
    task = getattr(app.state, "vm_scheduler_task", None)
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
