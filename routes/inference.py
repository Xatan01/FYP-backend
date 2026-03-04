from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from services.model_inference import (
    ask_gemma_model,
    ask_hint_model,
    get_models_health,
)

router = APIRouter(tags=["inference"])


class GenerateRequest(BaseModel):
    prompt: str
    model: Literal["finetuned", "gemma"] = "finetuned"


@router.post("/generate")
def generate(req: GenerateRequest):
    if req.model == "gemma":
        text = ask_gemma_model(req.prompt)
    else:
        text = ask_hint_model(req.prompt)
    return {"response": text}


@router.get("/health/models")
def health_models():
    return get_models_health()
