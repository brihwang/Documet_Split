from __future__ import annotations

import json
import os
import ssl
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def load_env(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        os.environ[name.strip()] = value.strip().strip('"').strip("'")


def request_json(url: str, api_key: str, payload: dict | None = None) -> tuple[int, dict | str]:
    headers = {"Authorization": f"Bearer {api_key}"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(url, data=data, headers=headers, method="POST" if payload is not None else "GET")
    try:
        with urlopen(request, timeout=30, context=ssl_context()) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body) if body else {}
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, body
    except URLError as exc:
        return 0, f"Network error: {exc}"


def ssl_context() -> ssl.SSLContext:
    try:
        import certifi  # type: ignore

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def redacted(value: str) -> str:
    if not value:
        return "missing"
    return f"set, length={len(value)}, prefix={value[:6]}..."


def main() -> int:
    load_env()
    api_key = os.environ.get("LLM_GATEWAY_API_KEY", "")
    base_url = os.environ.get("LLM_GATEWAY_BASE_URL", "https://api.llmgateway.io/v1").rstrip("/")
    models = llm_gateway_models()
    model = models[0] if models else ""
    provider = os.environ.get("AI_PROVIDER", "")

    print("Loaded configuration:")
    print(f"  AI_PROVIDER={provider or 'missing'}")
    print(f"  LLM_GATEWAY_API_KEY={redacted(api_key)}")
    print(f"  LLM_GATEWAY_BASE_URL={base_url or 'missing'}")
    print(f"  LLM_GATEWAY_MODEL={model or 'missing'}")
    print(f"  LLM_GATEWAY_FALLBACK_MODELS={', '.join(models[1:]) or 'none'}")

    if provider.lower() not in {"llmgateway", "gateway"}:
        print("\nAI_PROVIDER is not set to llmgateway, so docusplit will not call the API.")
        return 2
    if not api_key or not base_url or not model:
        print("\nMissing one or more required LLM Gateway settings.")
        return 2

    print("\nChecking /models...")
    status, models_response = request_json(f"{base_url}/models", api_key)
    print(f"  HTTP {status}")
    model_ids: list[str] = []
    if isinstance(models_response, dict):
        model_ids = [
            str(item.get("id"))
            for item in models_response.get("data", [])
            if isinstance(item, dict) and item.get("id")
        ]
    if model_ids:
        print(f"  Models visible to this key: {len(model_ids)}")
        for item in models:
            print(f"  Model found: {item}: {'yes' if item in model_ids else 'no'}")
        missing = [item for item in models if item not in model_ids]
        if missing:
            provider_terms = (
                "anthropic",
                "claude",
                "sonnet",
                "opus",
                "haiku",
                "gemini",
                "google",
                "gpt",
                "oss",
                "openai",
                "groq",
                "llama",
            )
            matching = [item for item in model_ids if any(term in item.lower() for term in provider_terms)]
            matching = sorted(set(matching))
            if matching:
                print("  Relevant-looking model IDs:")
                for item in matching:
                    print(f"    - {item}")
            else:
                print("  No Google/Gemini/Groq/Llama-looking model IDs were visible to this key.")
                print("  First 25 visible model IDs:")
                for item in model_ids[:25]:
                    print(f"    - {item}")
    else:
        print("  Could not read model IDs from response:")
        print(json.dumps(models_response, indent=2) if isinstance(models_response, dict) else models_response)

    print("\nMaking tiny chat completion requests...")
    failures = 0
    for item in models:
        payload = {
            "model": item,
            "messages": [{"role": "user", "content": "Reply with only: ok"}],
            "temperature": 0,
            "max_tokens": 5,
        }
        status, completion_response = request_json(f"{base_url}/chat/completions", api_key, payload)
        print(f"  {item}: HTTP {status}")
        if status == 200 and isinstance(completion_response, dict):
            content = (
                completion_response.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
            print(f"    Success. Response: {content!r}")
            continue

        failures += 1
        print("    Request failed. Gateway response:")
        print(json.dumps(completion_response, indent=2) if isinstance(completion_response, dict) else completion_response)
    return 1 if failures else 0


def llm_gateway_models() -> list[str]:
    primary = os.environ.get("LLM_GATEWAY_MODEL", "")
    fallbacks = os.environ.get("LLM_GATEWAY_FALLBACK_MODELS", "")
    models = [primary, *fallbacks.split(",")]
    cleaned = []
    for model in models:
        model = model.strip()
        if model and model not in cleaned:
            cleaned.append(model)
    return cleaned


if __name__ == "__main__":
    raise SystemExit(main())
