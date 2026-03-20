import os
from pathlib import Path
from typing import Any

import requests
from fastapi import HTTPException


def get_ollama_url() -> str:
    return os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").strip()


def get_model_gemma_original() -> str:
    return (
        os.getenv("MODEL_GEMMA_ORIGINAL", "").strip()
        or os.getenv("OLLAMA_HINT_MODEL", "").strip()
        or "gemma3:12b"
    )


def get_ollama_timeout_seconds() -> float:
    raw = os.getenv("OLLAMA_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return 90.0
    try:
        return max(float(raw), 1.0)
    except ValueError:
        return 90.0


def get_ollama_keep_alive() -> str:
    return os.getenv("OLLAMA_KEEP_ALIVE", "10m").strip() or "10m"


def get_gemma_model_path() -> str:
    # Backward compatibility for existing env names.
    return (
        os.getenv("GEMMA_MODEL_PATH", "").strip()
        or os.getenv("MODEL_PATH", "").strip()
    )


def validate_model_env() -> None:
    ollama_url = get_ollama_url()
    gemma_model = get_model_gemma_original()

    if not ollama_url:
        raise RuntimeError("OLLAMA_URL is empty.")
    if not gemma_model and not get_gemma_model_path():
        raise RuntimeError("Set MODEL_GEMMA_ORIGINAL or GEMMA_MODEL_PATH.")


def _ask_ollama_model(prompt: str, model_name: str) -> str:
    clean_prompt = str(prompt or "").strip()
    if not clean_prompt:
        raise HTTPException(status_code=422, detail="Prompt is required.")
    if not model_name:
        raise HTTPException(status_code=500, detail="Model name is not configured.")

    url = f"{get_ollama_url().rstrip('/')}/api/generate"
    options = {
        "num_ctx": _int_env("OLLAMA_NUM_CTX", 2048),
        "temperature": _float_env("OLLAMA_TEMPERATURE", 0.2),
    }
    num_predict = _optional_int_env("OLLAMA_NUM_PREDICT")
    if num_predict is not None:
        options["num_predict"] = num_predict

    payload = {
        "model": model_name,
        "prompt": clean_prompt,
        "stream": False,
        "keep_alive": get_ollama_keep_alive(),
        "options": options,
    }

    try:
        res = requests.post(url, json=payload, timeout=get_ollama_timeout_seconds())
    except requests.Timeout:
        raise HTTPException(status_code=504, detail="Ollama request timed out.")
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Failed to reach Ollama: {exc}")

    if res.status_code >= 400:
        detail = None
        try:
            detail = res.json()
        except ValueError:
            detail = res.text
        raise HTTPException(status_code=502, detail=f"Ollama error: {detail}")

    try:
        data = res.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="Invalid JSON response from Ollama.")

    answer = str(data.get("response", "")).strip()
    if not answer:
        raise HTTPException(status_code=502, detail=f"Model '{model_name}' returned an empty response.")
    return answer


_LLAMA_INSTANCE: Any | None = None
_LLAMA_MODEL_PATH: str | None = None


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _optional_int_env(name: str) -> int | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _load_llama_class():
    try:
        from llama_cpp import Llama  # lazy import
        return Llama
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail=(
                "llama_cpp is not installed. Install llama-cpp-python to use GEMMA_MODEL_PATH. "
                f"Import error: {exc}"
            ),
        )


def _get_llama():
    global _LLAMA_INSTANCE, _LLAMA_MODEL_PATH

    model_path = get_gemma_model_path()
    if not model_path:
        raise HTTPException(status_code=503, detail="GEMMA_MODEL_PATH is not configured.")
    if not Path(model_path).exists():
        raise HTTPException(status_code=503, detail=f"GEMMA model file does not exist: {model_path}")

    if _LLAMA_INSTANCE is None or _LLAMA_MODEL_PATH != model_path:
        try:
            Llama = _load_llama_class()
            _LLAMA_INSTANCE = Llama(
                model_path=model_path,
                n_ctx=_int_env("GEMMA_N_CTX", 4096),
                n_threads=_int_env("GEMMA_N_THREADS", os.cpu_count() or 4),
                n_gpu_layers=_int_env("GEMMA_N_GPU_LAYERS", 0),
            )
            _LLAMA_MODEL_PATH = model_path
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"Failed to load local GEMMA model: {exc}")

    return _LLAMA_INSTANCE


def ask_gemma_model(prompt: str) -> str:
    # If a local GGUF path is configured, prefer local llama.cpp inference.
    gemma_path = get_gemma_model_path()
    if gemma_path:
        llm = _get_llama()
        clean_prompt = str(prompt or "").strip()
        if not clean_prompt:
            raise HTTPException(status_code=422, detail="Prompt is required.")
        try:
            result = llm(clean_prompt, max_tokens=512, temperature=0.2)
            text = (
                (result.get("choices") or [{}])[0].get("text", "")
                if isinstance(result, dict)
                else ""
            )
            answer = str(text).strip()
            if not answer:
                raise HTTPException(status_code=502, detail="Local GEMMA returned an empty response.")
            return answer
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"Local GEMMA inference failed: {exc}")

    # Otherwise call original Gemma model hosted in Ollama.
    return _ask_ollama_model(prompt, get_model_gemma_original())


def get_models_health() -> dict:
    ollama_url = get_ollama_url()
    gemma_model = get_model_gemma_original()
    gemma_path = get_gemma_model_path()
    ollama_reachable = False
    ollama_error = None

    try:
        res = requests.get(f"{ollama_url.rstrip('/')}/api/tags", timeout=5)
        ollama_reachable = res.status_code == 200
        if res.status_code >= 400:
            ollama_error = f"HTTP {res.status_code}"
    except requests.RequestException as exc:
        ollama_error = str(exc)

    local_gemma = {
        "path_configured": bool(gemma_path),
        "path_exists": bool(gemma_path and Path(gemma_path).exists()),
        "path": gemma_path or None,
    }

    if gemma_path:
        try:
            _load_llama_class()
            local_gemma["llama_cpp_available"] = True
            local_gemma["error"] = None
        except HTTPException as exc:
            local_gemma["llama_cpp_available"] = False
            local_gemma["error"] = exc.detail
    else:
        local_gemma["llama_cpp_available"] = None
        local_gemma["error"] = None

    return {
        "url": ollama_url,
        "reachable": ollama_reachable,
        "gemma_model": gemma_model,
        "local_gemma": local_gemma,
        "error": ollama_error,
    }
