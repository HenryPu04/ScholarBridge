from fastapi import APIRouter

router = APIRouter(prefix="/inquiries", tags=["inquiries"])


@router.post("/")
async def send_inquiry():
    """Send inquiry to researcher. Stub — implemented in Phase 4."""
    return {"status": "not_implemented"}
