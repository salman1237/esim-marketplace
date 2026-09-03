"""Loads the base translation strings shipped with the platform from
app/locales/*.json — exact copies of frontend/src/locales/*.json, duplicated
here because the backend and frontend have separate Docker build contexts
(see docker-compose.yml) so the backend container can't read the frontend
directory at build or run time. Keep these two directories in sync when
editing shipped strings.
"""
import json
from pathlib import Path

LOCALES_DIR = Path(__file__).resolve().parent.parent / "locales"

# Languages with real, hand-authored translations shipped in app/locales/.
SHIPPED_LOCALE_CODES = ["en", "bn", "ar", "es"]

# Additional languages the plan lists as "ships with" but that don't yet have
# hand-authored strings — these get English placeholders (via auto-translate)
# so they're immediately usable rather than blank, flagged for human review.
PLACEHOLDER_LANGUAGES = [
    ("fr", "French", "Français", "🇫🇷", False),
    ("de", "German", "Deutsch", "🇩🇪", False),
    ("zh", "Chinese", "中文", "🇨🇳", False),
    ("ja", "Japanese", "日本語", "🇯🇵", False),
    ("ru", "Russian", "Русский", "🇷🇺", False),
    ("hi", "Hindi", "हिन्दी", "🇮🇳", False),
    ("tr", "Turkish", "Türkçe", "🇹🇷", False),
    ("pt", "Portuguese", "Português", "🇵🇹", False),
    ("it", "Italian", "Italiano", "🇮🇹", False),
]


def _load(code: str) -> dict:
    path = LOCALES_DIR / f"{code}.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


EN_TRANSLATIONS = _load("en")


def flatten(nested: dict) -> list[tuple[str, str, str]]:
    """Returns a flat list of (namespace, key, value) from a nested
    {namespace: {key: value}} shape."""
    return [
        (namespace, key, value)
        for namespace, entries in nested.items()
        for key, value in entries.items()
    ]


def load_shipped_translations(code: str) -> list[tuple[str, str, str]]:
    """Flat (namespace, key, value) rows for a shipped language, i.e. one
    with a real app/locales/{code}.json file (en/bn/ar/es)."""
    return flatten(_load(code))
