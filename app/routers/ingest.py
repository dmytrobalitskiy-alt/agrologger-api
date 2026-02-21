from fastapi import APIRouter

router = APIRouter(
    prefix="/ingest",
    tags=["Ingest"]
)

@router.get("/test")
def test_ingest():
    return {"status": "ok"}
