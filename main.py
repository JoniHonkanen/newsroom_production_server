# main.py
import os
import sys
import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
import strawberry
from strawberry.fastapi import GraphQLRouter
import logging
from datetime import datetime
from contextlib import asynccontextmanager
from dotenv import load_dotenv

from resolvers import Query
from database import get_db_pool, close_db_pool
from twilio_phone_service import setup_twilio_routes
from vonage_phone_service import setup_vonage_routes

# Load environment variables
load_dotenv()

# Windows event loop policy fix
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

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

# TODO:: REMEMBER UPDATE THESE WHEN WE GO FOR PRODUCTION
# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://192.168.1.102:3000",  # Example IP address, replace with your frontend's address
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

# Setup Twilio routes (for interview phone calls)
#setup_twilio_routes(app)
setup_vonage_routes(app)


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
        "message": "News GraphQL API with Twilio Integration",
        "version": "1.0.0",
        "endpoints": {
            "graphql": "/graphql",
            "health": "/health",
            "docs": "/docs",
            "incoming_call": "/incoming-call",
            "trigger_call": "/trigger-call (POST)",
            "media_stream": "/media-stream (WebSocket)",
        },
    }


# Serve static files (e.g., article images)
# BECAUSE WE STILL DONT HAVE ANYPLACE TO STORE IMAGES... WE NEED TO SERVE THEM SOMEHOW
# THATS WHY WE DO THIS "STUPID" WAY TO DO IT :D
# TODO:: REMEMBER TO CHANGE PATH WHERE IS YOUR "NEWSROOM PRODUCTION"-program running
app.mount(
    "/static",
    StaticFiles(directory=os.getenv("STATIC_FILE_PATH")),
    name="static",
)

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 4000))
    host = os.getenv("HOST", "0.0.0.0")

    logger.info(f"Starting server on {host}:{port}")

    uvicorn.run("main:app", host=host, port=port, reload=True, log_level="info")
