# database.py
import asyncpg
import os
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

# Database connection pool
db_pool = None

async def get_db_pool():
    """Get or create database connection pool"""
    global db_pool
    if db_pool is None:
        try:
            db_pool = await asyncpg.create_pool(
                host=os.getenv('DB_HOST'),
                port=int(os.getenv('DB_PORT', 5432)),
                database=os.getenv('DB_NAME'),
                user=os.getenv('DB_USER'),
                password=os.getenv('DB_PASSWORD'),
                min_size=1,
                max_size=10
            )
            print('Connected to PostgreSQL database')
            logger.info("Database connection pool created successfully")
        except Exception as e:
            print(f'PostgreSQL pool error: {e}')
            logger.error(f"Failed to create database pool: {e}")
            raise
    return db_pool

async def close_db_pool():
    """Close database connection pool"""
    global db_pool
    if db_pool:
        await db_pool.close()
        db_pool = None
        logger.info("Database connection pool closed")