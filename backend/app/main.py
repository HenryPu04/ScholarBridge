from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import inquiries_router, papers_router, researchers_router, summaries_router
from app.services.semantic_scholar import get_semantic_scholar_service

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize Pinecone index on startup (creates it if it doesn't exist).
    # Skipped in mock mode so no credentials are required during local dev.
    if not settings.use_mock_api:
        from app.services.pinecone_client import get_pinecone_client
        get_pinecone_client()
    yield


app = FastAPI(title="ScholarBridge API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(papers_router, prefix="/api/v1")
app.include_router(summaries_router, prefix="/api/v1")
app.include_router(researchers_router, prefix="/api/v1")
app.include_router(inquiries_router, prefix="/api/v1")

# Swap in the mock Semantic Scholar service when USE_MOCK_API=true.
# All endpoints that Depend(get_semantic_scholar_service) receive the mock
# automatically — no changes needed in individual routers.
if settings.use_mock_api:
    from app.services.mock_semantic_scholar import get_mock_semantic_scholar_service
    app.dependency_overrides[get_semantic_scholar_service] = get_mock_semantic_scholar_service


@app.get("/healthz")
async def health_check():
    return {"status": "ok", "mock_mode": settings.use_mock_api}
