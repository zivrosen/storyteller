from models import Character
from utils import estimate_reading_time, target_words, format_characters


def test_reading_time_short_text():
    out = estimate_reading_time("one two three")
    assert out.endswith("s")


def test_reading_time_long_text():
    text = " ".join(["word"] * 600)
    out = estimate_reading_time(text, wpm=150)
    assert "m" in out


def test_target_words_known_lengths():
    assert target_words("short") == 350
    assert target_words("medium") == 550
    assert target_words("long") == 750


def test_target_words_unknown_falls_back_to_medium():
    assert target_words("colossal") == 550


def test_format_characters_empty():
    assert "(none" in format_characters([])


def test_format_characters_list():
    out = format_characters([Character("Alice", "girl"), Character("Bob", "cat")])
    assert "Alice (girl)" in out
    assert "Bob (cat)" in out
