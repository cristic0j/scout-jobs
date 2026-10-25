"""Thin Gemini wrapper: prompt (+ CV files) in, parsed JSON out."""
import json
import os
import time

MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
# Tried in order when a model keeps answering "high demand" (503) or rate limits (429).
FALLBACKS = list(dict.fromkeys([MODEL, "gemini-3.6-flash", "gemini-3.5-flash-lite"]))
TIMEOUT_MS = 90_000  # a busy model sometimes holds the connection instead of answering 503
_client = None
_busy = set()  # models that were busy earlier in this run


class MissingKey(RuntimeError):
    pass


def client():
    global _client
    if _client is None:
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise MissingKey("GEMINI_API_KEY is not set. Add `export GEMINI_API_KEY=...` to ~/.zshrc "
                             "and open a new terminal.")
        from google import genai
        from google.genai import types
        # attempts=1: retries/fallback are handled in ask_json, the SDK's own retries made busy models hang for minutes.
        _client = genai.Client(api_key=key, http_options=types.HttpOptions(
            timeout=TIMEOUT_MS, retry_options=types.HttpRetryOptions(attempts=1)))
    return _client


def _parts(files):
    from google.genai import types
    out = []
    for path in files:
        if path.suffix.lower() == ".pdf":
            out.append(types.Part.from_bytes(data=path.read_bytes(), mime_type="application/pdf"))
        else:
            out.append(f"--- {path.name} ---\n{path.read_text(errors='ignore')}")
    return out


def ask_json(prompt, schema, files=(), system=""):
    """One structured Gemini call. A busy model (503/429/timeout) gets one try, then the next model is used
    for the rest of the run; the last model is retried with backoff."""
    import httpx
    from google.genai import errors, types
    config = types.GenerateContentConfig(system_instruction=system or None, temperature=0.2,
                                         response_mime_type="application/json", response_json_schema=schema)
    contents = _parts(files) + [prompt]
    models = [m for m in FALLBACKS if m not in _busy] or FALLBACKS[-1:]
    for i, model in enumerate(models):
        last = i == len(models) - 1
        tries = 4 if last else 1
        for attempt in range(tries):
            try:
                r = client().models.generate_content(model=model, contents=contents, config=config)
                return json.loads(r.text)
            except (errors.APIError, httpx.TimeoutException) as e:
                busy = isinstance(e, httpx.TimeoutException) or e.code in (429, 500, 502, 503, 504)
                if not busy or (last and attempt == tries - 1):
                    raise
                if attempt < tries - 1:
                    time.sleep(5 * 2 ** attempt)
        _busy.add(model)
        print(f"  {model} is busy, using {models[i + 1]} instead")
