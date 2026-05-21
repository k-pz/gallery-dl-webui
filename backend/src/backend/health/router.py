from fastapi import APIRouter

from backend import __version__

router = APIRouter(tags=["health"])


@router.get("/health", operation_id="getHealth")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}
