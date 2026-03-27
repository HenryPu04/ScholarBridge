from fastapi import APIRouter

router = APIRouter(prefix="/researchers", tags=["researchers"])


@router.get("/{author_id}")
async def get_researcher_profile(author_id: str):
    """Public researcher profile. Stub — implemented in Phase 4."""
    return {"author_id": author_id, "status": "profile_not_claimed"}
