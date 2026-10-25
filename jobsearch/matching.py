import re


def keyword_pattern(words):
    """One case-insensitive regex matching any of `words`, or None if the list is empty.

    Keywords of 3 characters or fewer match whole words only, so 'go' doesn't hit 'google'.
    Longer ones match anywhere, which catches Dutch compounds like 'softwareontwikkelaar'.
    Prefix a keyword with 're:' to pass a raw regex.
    """
    parts = []
    for w in words:
        w = w.strip()
        if not w:
            continue
        if w.startswith("re:"):
            parts.append(f"(?:{w[3:]})")
        elif len(w) <= 3:
            parts.append(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])")
        else:
            parts.append(re.escape(w))
    return re.compile("|".join(parts), re.I) if parts else None
