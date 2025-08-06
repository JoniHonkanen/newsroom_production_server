# main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import strawberry
from strawberry.fastapi import GraphQLRouter
import os
import logging
from datetime import datetime
from contextlib import asynccontextmanager

from resolvers import Query
from database import get_db_pool, close_db_pool

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Lifespan event handler
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    try:
        await get_db_pool()
        logger.info("🚀 News GraphQL API started successfully")
        logger.info(f"📊 Health check available at /health")
        logger.info(f"🔍 GraphQL endpoint available at /graphql")
        logger.info(f"📖 API docs available at /docs")
    except Exception as e:
        logger.error(f"❌ Failed to start application: {e}")
        raise

    yield

    # Shutdown
    try:
        await close_db_pool()
        logger.info("🛑 News GraphQL API shutdown completed")
    except Exception as e:
        logger.error(f"❌ Error during shutdown: {e}")


# Create FastAPI app
app = FastAPI(
    title="News GraphQL API",
    version="1.0.0",
    description="GraphQL API for news articles with FastAPI and Strawberry",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://192.168.1.102:3000", # Example IP address, replace with your frontend's address
        "http://localhost:3001",  # Add more origins as needed
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create GraphQL schema
schema = strawberry.Schema(query=Query)
graphql_app = GraphQLRouter(schema)

# Mount GraphQL endpoint
app.include_router(graphql_app, prefix="/graphql")


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "OK",
        "timestamp": datetime.now().isoformat(),
        "service": "News GraphQL API",
        "version": "1.0.0",
    }


# Root endpoint
@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "message": "News GraphQL API",
        "version": "1.0.0",
        "graphql_endpoint": "/graphql",
        "health_check": "/health",
        "docs": "/docs",
    }


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 4000))
    host = os.getenv("HOST", "0.0.0.0")

    logger.info(f"Starting server on {host}:{port}")

    uvicorn.run("main:app", host=host, port=port, reload=True, log_level="info")
