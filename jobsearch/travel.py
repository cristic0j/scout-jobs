"""Travel time from home to a job's city, estimated by Gemini and cached per search."""
import json
import re

from . import llm

SCHEMA = {"type": "object", "properties": {"times": {"type": "array", "items": {
    "type": "object",
    "properties": {"place": {"type": "string"},
                   "minutes": {"type": "integer", "description": "one way, door to door; -1 if unknown"}},
    "required": ["place", "minutes"]}}}, "required": ["times"]}
SYSTEM = """You estimate one-way door-to-door travel time by public transport (train/bus) on a normal
weekday morning, from the candidate's home to a job location. Use real geography and be realistic, not
optimistic. A region (e.g. "Randstad") means its main city. Answer -1 for places you don't know."""
BATCH = 60


def place_key(location):
    """'Amsterdam Area' / 'Greater Utrecht' / 'Eindhoven, North Brabant, Netherlands' → 'amsterdam' / ..."""
    first = (location or "").split(",")[0]
    first = re.sub(r"\b(metropolitan area|area|greater|region|regio|omgeving)\b", "", first, flags=re.I)
    return " ".join(first.split()).lower()


def text(minutes):
    if minutes is None:
        return ""
    h, m = divmod(int(minutes), 60)
    return f"~{m} min" if not h else f"~{h} h" + (f" {m:02d}" if m else "")


def minutes(search, home, country, locations):
    """{place_key: minutes or None}. Asks Gemini only for places not in the cache."""
    cache = json.loads(search.travel_path.read_text()) if search.travel_path.exists() else {}
    prefix = f"{home.lower()}|"
    keys = sorted({place_key(l) for l in locations if place_key(l)})
    vague = {country.lower(), "the " + country.lower(), "remote", "hybrid", "nederland"}  # not a place
    todo = [k for k in keys if prefix + k not in cache and k not in vague]
    for i in range(0, len(todo), BATCH):
        batch = todo[i:i + BATCH]
        try:
            out = llm.ask_json(f"Home: {home}, {country}\nJob locations:\n" + "\n".join(batch)
                               + "\n\nReturn one entry per job location, `place` copied exactly.", SCHEMA,
                               system=SYSTEM)
        except Exception as e:  # no key / API down: unknown travel, the matcher still sees the job
            print(f"  Travel times unavailable ({e.__class__.__name__}); jobs kept for the matcher.")
            break
        for t in out.get("times") or []:
            k = place_key(str(t.get("place", "")))
            if k in batch:
                m = t.get("minutes")
                cache[prefix + k] = m if isinstance(m, int) and m >= 0 else None
    if todo:
        search.travel_path.write_text(json.dumps(cache, indent=1, ensure_ascii=False))
    return {k: None if k in vague else cache.get(prefix + k) for k in keys}
