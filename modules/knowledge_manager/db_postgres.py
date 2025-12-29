# File: knowledge_manager/db_postgres.py
"""
PostgreSQL adapter for knowledge_manager.
Provides PostgreSQL connection management with an API compatible with sqlite3.
"""
import os
import psycopg2
import psycopg2.extras
from typing import Optional
from contextlib import contextmanager


def get_postgres_connection_string() -> Optional[str]:
    """
    Build PostgreSQL connection string from environment variables.
    Returns None if not configured for PostgreSQL.
    """
    db_type = os.getenv("KM_DB_TYPE", "sqlite").lower()

    if db_type != "postgresql":
        return None

    host = os.getenv("KM_POSTGRES_HOST", "localhost")
    port = os.getenv("KM_POSTGRES_PORT", "5432")
    database = os.getenv("KM_POSTGRES_DB", "knowledge_manager")
    user = os.getenv("KM_POSTGRES_USER", "km_user")
    password = os.getenv("KM_POSTGRES_PASSWORD")

    if not password:
        raise ValueError(
            "KM_POSTGRES_PASSWORD environment variable must be set when using PostgreSQL"
        )

    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


def get_postgres_connection() -> psycopg2.extensions.connection:
    """
    Establishes a connection to PostgreSQL database.

    Uses environment variables:
    - KM_POSTGRES_HOST (default: localhost)
    - KM_POSTGRES_PORT (default: 5432)
    - KM_POSTGRES_DB (default: knowledge_manager)
    - KM_POSTGRES_USER (default: km_user)
    - KM_POSTGRES_PASSWORD (required)
    """
    conn_string = get_postgres_connection_string()

    if not conn_string:
        raise ValueError("PostgreSQL not configured. Set KM_DB_TYPE=postgresql")

    # Parse connection string components
    host = os.getenv("KM_POSTGRES_HOST", "localhost")
    port = int(os.getenv("KM_POSTGRES_PORT", "5432"))
    database = os.getenv("KM_POSTGRES_DB", "knowledge_manager")
    user = os.getenv("KM_POSTGRES_USER", "km_user")
    password = os.getenv("KM_POSTGRES_PASSWORD")

    conn = psycopg2.connect(
        host=host,
        port=port,
        database=database,
        user=user,
        password=password,
        cursor_factory=psycopg2.extras.DictCursor
    )

    # Set autocommit to False for transaction control (like SQLite)
    conn.autocommit = False

    return conn


def use_postgresql() -> bool:
    """
    Check if PostgreSQL should be used based on environment variables.
    """
    return os.getenv("KM_DB_TYPE", "sqlite").lower() == "postgresql"


@contextmanager
def get_db_connection_context():
    """
    Context manager for database connections (PostgreSQL or SQLite).
    Automatically handles connection cleanup.

    Usage:
        with get_db_connection_context() as conn:
            cursor = conn.cursor()
            ...
    """
    if use_postgresql():
        conn = get_postgres_connection()
    else:
        # Import here to avoid circular dependency
        from .db import get_db_connection, get_default_db_path
        db_path = get_default_db_path()
        conn = get_db_connection(db_path)

    try:
        yield conn
    finally:
        conn.close()


def test_connection() -> bool:
    """
    Test PostgreSQL connection.
    Returns True if successful, False otherwise.
    """
    try:
        conn = get_postgres_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        result = cursor.fetchone()
        conn.close()
        return result[0] == 1
    except Exception as e:
        print(f"PostgreSQL connection test failed: {e}")
        return False
