from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import NullPool
import os
import sys
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = (os.getenv("DATABASE_URL") or "").strip()

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")

if DATABASE_URL.startswith("https://") or DATABASE_URL.startswith("http://"):
    raise RuntimeError(
        "DATABASE_URL must be a Postgres connection string, not a Supabase project URL. "
        "Use the connection string from Supabase Database settings."
    )

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

# psycopg async + Windows ProactorEventLoop is incompatible.
if sys.platform.startswith("win") and DATABASE_URL.startswith("postgresql+psycopg://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)

engine_kwargs = {"pool_pre_ping": True}

# Supabase PgBouncer in transaction/statement mode can break asyncpg prepared statements.
# Disable asyncpg statement caching and avoid SQLAlchemy-level pooling on asyncpg URLs.
if DATABASE_URL.startswith("postgresql+asyncpg://"):
    split = urlsplit(DATABASE_URL)
    query = dict(parse_qsl(split.query, keep_blank_values=True))
    query.setdefault("prepared_statement_cache_size", "0")
    DATABASE_URL = urlunsplit(
        (split.scheme, split.netloc, split.path, urlencode(query), split.fragment)
    )

    engine_kwargs["connect_args"] = {
        "statement_cache_size": 0,
    }
    engine_kwargs["poolclass"] = NullPool

engine = create_async_engine(DATABASE_URL, **engine_kwargs)
SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)
Base = declarative_base()

async def get_db():
    async with SessionLocal() as db:
        yield db


# Backward-compatible alias for modules still importing get_async_db.
get_async_db = get_db
