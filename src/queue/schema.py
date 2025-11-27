"""
Database schema initialization.

Handles database migration and schema setup.
"""
import os
import logging
from src.database.connection import get_db_connection

logger = logging.getLogger(__name__)


def init_database() -> None:
    """
    Initialize database schema if not exists.
    
    Reads and executes the migration file to create tables and functions.
    
    Raises:
        FileNotFoundError: If migration file doesn't exist
        psycopg2.Error: If database operation fails
    """
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # Read and execute migration file
                migration_path = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                    "migrations",
                    "001_initial_schema.sql"
                )
                if os.path.exists(migration_path):
                    with open(migration_path, 'r') as f:
                        cur.execute(f.read())
                    logger.info("Database schema initialized")
                else:
                    logger.warning(f"Migration file not found: {migration_path}")
                    raise FileNotFoundError(f"Migration file not found: {migration_path}")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise

