from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas import DescribeRequest, DescribeResponse

router = APIRouter(prefix='/v1')


@router.post('/describe', response_model=DescribeResponse)
async def describe_scene(payload: DescribeRequest):
    from app.main import app_state

    try:
        result = await app_state.describe_scene(payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return DescribeResponse(**result)


@router.post('/speak')
def speak_text(text: str, priority: str = 'P3'):
    from app.main import app_state

    return {'ok': app_state.speaker.say(text, priority), 'priority': priority}
