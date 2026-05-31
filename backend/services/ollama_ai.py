import json

import httpx

from config import settings


def ask_ollama(prompt: str, system: str = "You are a concise portfolio analysis assistant.") -> str | None:
    try:
        response = httpx.post(
            f"{settings.ollama_base_url.rstrip('/')}/api/generate",
            json={
                "model": settings.ollama_model,
                "system": system,
                "prompt": prompt,
                "stream": False,
            },
            timeout=60,
        )
        response.raise_for_status()
        return response.json().get("response")
    except Exception:
        return None


def extract_trade_from_text(text: str) -> dict | None:
    prompt = (
        "Extract a trade from this text as strict JSON with keys "
        "tradingsymbol, side, quantity, price, trade_date, confidence. "
        "Use null for unknown values. Text: "
        f"{text}"
    )
    output = ask_ollama(prompt, system="You extract Indian stock trades from text. Return only JSON.")
    if not output:
        return None
    try:
        start = output.find("{")
        end = output.rfind("}") + 1
        return json.loads(output[start:end])
    except Exception:
        return None
