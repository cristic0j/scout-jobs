"""Thin Gemini wrapper: prompt (+ CV files) in, parsed JSON out."""
import json
import os
import time

MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
_client = None


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
        _client = genai.Client(api_key=key)
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
    """One structured Gemini call. Retries rate limits and server errors with backoff."""
    from google.genai import errors, types
    config = types.GenerateContentConfig(system_instruction=system or None, temperature=0.2,
                                         response_mime_type="application/json", response_json_schema=schema)
    contents = _parts(files) + [prompt]
    for attempt in range(4):
        try:
            r = client().models.generate_content(model=MODEL, contents=contents, config=config)
            return json.loads(r.text)
        except errors.APIError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < 3:
                time.sleep(5 * 2 ** attempt)
                continue
            raise
