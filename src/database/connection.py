"""
PostgreSQL connection pool management.

Handles connection pooling, connection lifecycle, and database access.
"""
import os
import logging
import psycopg2
from psycopg2.pool import ThreadedConnectionPool
from typing import Optional
from contextlib import contextmanager
from dotenv import load_dotenv

# Load environment variables
load_dotenv(override=True)

logger = logging.getLogger(__name__)

# PostgreSQL connection settings
POSTGRES_URL = os.getenv("POSTGRES_URL", "postgresql://postgres:postgres@localhost:5432/rgb_node")
POSTGRES_MIN_CONNECTIONS = int(os.getenv("POSTGRES_MIN_CONNECTIONS", "2"))
POSTGRES_MAX_CONNECTIONS = int(os.getenv("POSTGRES_MAX_CONNECTIONS", "10"))

# Connection pool (singleton)
_connection_pool: Optional[ThreadedConnectionPool] = None


def get_connection_pool() -> ThreadedConnectionPool:
    """
    Get or create PostgreSQL connection pool (singleton pattern).
    
    Returns:
        ThreadedConnectionPool instance
        
    Raises:
        psycopg2.Error: If connection pool creation fails
    """
    global _connection_pool
    if _connection_pool is None:
        try:
            _connection_pool = ThreadedConnectionPool(
                POSTGRES_MIN_CONNECTIONS,
                POSTGRES_MAX_CONNECTIONS,
                POSTGRES_URL
            )
            logger.info("PostgreSQL connection pool created")
        except Exception as e:
            logger.error(f"Failed to create PostgreSQL connection pool: {e}")
            raise
    return _connection_pool


@contextmanager
def get_db_connection():
    """
    Get database connection from pool (context manager).
    
    Automatically commits on success, rolls back on error, and returns
    connection to pool when done.
    
    Yields:
        psycopg2.connection: Database connection
        
    Example:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
    """
    pool = get_connection_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Database error: {e}")
        raise
    finally:
        pool.putconn(conn)


def close_connection_pool() -> None:
    """
    Close all connections in the pool.
    Should be called on application shutdown.
    """
    global _connection_pool
    if _connection_pool is not None:
        _connection_pool.closeall()
        _connection_pool = None
        logger.info("PostgreSQL connection pool closed")

