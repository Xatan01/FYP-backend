from fastapi import APIRouter
from pydantic import BaseModel

from services.model_inference import (
    ask_gemma_model,
    get_models_health,
)

router = APIRouter(tags=["inference"])


class GenerateRequest(BaseModel):
    prompt: str


@router.post("/generate")
def generate(req: GenerateRequest):
    text = ask_gemma_model(req.prompt)
    return {"response": text}


@router.get("/health/models")
def health_models():
    return get_models_health()
