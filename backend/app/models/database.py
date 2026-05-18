# backend/app/models/database.py
#
# PURPOSE: Database connection and session management
#
# WHY SQLALCHEMY?
# SQLAlchemy is Python's most popular ORM (Object Relational Mapper).
# ORM means we write Python classes instead of raw SQL to define tables.
# SQLAlchemy translates our Python classes into SQL automatically.
#
# WHY SQLITE?
# - Zero setup — single file on your computer
# - No separate database server needed
# - Perfect for this scale (hundreds of orders, not millions)
# - Can switch to PostgreSQL later with one config change

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from pathlib import Path
import sys
import os

sys.path.append(
    os.path.join(os.path.dirname(__file__), '..', '..', '..')
)

from app.core.config import settings

# Database file lives in backend/ folder
# Path(__file__) = this file
# .parent = models/ folder
# .parent.parent = app/ folder  
# .parent.parent.parent = backend/ folder
BASE_DIR = Path(__file__).parent.parent.parent
DB_PATH  = BASE_DIR / "rimitlayers.db"

# Connection string format: dialect+driver://path/to/file
# sqlite:/// = three slashes for relative, four for absolute path
DATABASE_URL = f"sqlite:///{DB_PATH}"

# Engine is the core interface to the database
# connect_args={"check_same_thread": False} is required for SQLite
# when used with FastAPI (which runs in multiple threads)
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False  # Set to True to see all SQL queries in terminal (useful for debugging)
)

# SessionLocal is a factory for database sessions
# Each request to our API gets its own session
# autocommit=False means we control when changes are saved
# autoflush=False means we control when changes are sent to DB
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

# Base class that all our models (tables) inherit from
# This is how SQLAlchemy knows which classes are database tables
Base = declarative_base()


def get_db():
    """
    Database session generator — used by FastAPI dependency injection.
    
    WHY A GENERATOR?
    FastAPI uses dependency injection for database sessions.
    The 'yield' creates the session, hands it to the route handler,
    and the finally block ensures it's always closed — even if an
    error occurs. This prevents connection leaks.
    
    INTERVIEW POINT:
    "I used FastAPI's dependency injection pattern for database
     sessions. Each request gets its own session that's automatically
     closed after the request completes — this prevents connection
     leaks and ensures data consistency."
    
    Usage in FastAPI routes:
        @app.get("/sales")
        def get_sales(db: Session = Depends(get_db)):
            return db.query(Sale).all()
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables():
    """
    Creates all database tables if they don't exist.
    Called once when the application starts.
    
    WHY NOT DROP AND RECREATE?
    We never drop existing tables — that would delete your business data.
    'create_all' only creates tables that don't exist yet — safe to call
    every time the app starts.
    """
    # Import all models here so Base knows about them
    # This must happen before create_all()
    from app.models import sale, message, inventory, fee, expense  # noqa
    
    Base.metadata.create_all(bind=engine)
    print(f"✅ Database ready at: {DB_PATH}")