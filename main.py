import asyncio
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes import auth
from routes import inference
from routes import lesson
from routes import market
from routes import quiz
from services.model_inference import validate_model_env
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
app.include_router(inference.router)


@app.on_event("startup")
def startup_checks():
    validate_model_env()
