from models import Character


LENGTH_TO_WORDS = {
    "short": 350,
    "medium": 550,
    "long": 750,
}


def target_words(length: str) -> int:
    return LENGTH_TO_WORDS.get(length, 550)


def format_characters(chars: list[Character]) -> str:
    if not chars:
        return "(none specified)"
    return ", ".join(f"{c.name} ({c.kind})" for c in chars)


def estimate_reading_time(text: str, wpm: int = 150) -> str:
    """Approximate read-aloud time. 150 wpm matches a calm bedtime cadence."""
    words = len(text.split())
    seconds = (words / wpm) * 60 if wpm > 0 else 0
    minutes, secs = divmod(int(round(seconds)), 60)
    if minutes == 0:
        return f"{secs}s"
    return f"{minutes}m {secs}s"
