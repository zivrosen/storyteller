from prompts import (
    CATEGORIZER_PROMPT,
    PLANNER_PROMPT,
    STORYTELLER_PROMPT,
    REFINER_PROMPT,
    USER_TWEAK_PROMPT,
    JUDGE_PROMPT,
)


def test_categorizer_renders_with_user_input():
    out = CATEGORIZER_PROMPT.format(user_input="A story about a dog")
    assert "A story about a dog" in out
    assert "JSON" in out or "json" in out


def test_planner_renders_with_all_fields():
    out = PLANNER_PROMPT.format(
        category="animals",
        characters="Alice (girl), Bob (cat)",
        themes="friendship, curiosity",
        tone_hint="gentle",
        user_input="Alice and Bob find a star",
    )
    assert "animals" in out
    assert "Alice (girl)" in out
    assert "WIND_DOWN" in out
    assert "friendship" in out


def test_storyteller_includes_outline_beats_and_word_target():
    out = STORYTELLER_PROMPT.format(
        target_words=550,
        tone_hint="cozy",
        title="The Quiet Garden",
        setup="setup text",
        spark="spark text",
        resolution="resolution text",
        wind_down="wind down text",
    )
    assert "setup text" in out
    assert "spark text" in out
    assert "resolution text" in out
    assert "wind down text" in out
    assert "550" in out
    assert "wind-down" in out.lower()


def test_refiner_renders_with_critique():
    out = REFINER_PROMPT.format(
        critique_block="- safety (score 2/5): too scary",
        draft="Once upon a time...",
    )
    assert "too scary" in out
    assert "Once upon a time" in out
    assert "do NOT rewrite" in out


def test_user_tweak_includes_request_and_draft():
    out = USER_TWEAK_PROMPT.format(user_request="make it shorter", draft="Once upon a time...")
    assert "make it shorter" in out
    assert "Once upon a time" in out


def test_judge_renders_with_story_and_dimensions():
    out = JUDGE_PROMPT.format(story="Once upon a time...")
    assert "Once upon a time" in out
    assert "overall_pass" in out
    assert "ending_calmness" in out
    assert "character_consistency" in out
