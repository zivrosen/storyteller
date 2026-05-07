import json
from unittest.mock import patch

import pytest

from pipeline import (
    generate_story,
    apply_user_tweak,
    categorize,
    MAX_REFINEMENTS,
    PipelineCancelled,
)
from models import Draft
from judge import DIMENSIONS


def _judge_with(score_overrides: dict, default: int = 5, overall: bool = False, fix: str = "x") -> str:
    scores = {dim: {"score": default, "critique": "ok"} for dim in DIMENSIONS}
    for dim, s in score_overrides.items():
        scores[dim] = {"score": s, "critique": "needs work"}
    return json.dumps(
        {"scores": scores, "overall_pass": overall, "top_priority_fix": fix}
    )


def _judge_resp(score: int = 5, overall: bool = True, fix=None) -> str:
    return json.dumps(
        {
            "scores": {dim: {"score": score, "critique": "ok"} for dim in DIMENSIONS},
            "overall_pass": overall,
            "top_priority_fix": fix,
        }
    )


CAT_RESPONSE = json.dumps(
    {
        "category": "animals",
        "characters": [
            {"name": "Alice", "kind": "girl"},
            {"name": "Bob", "kind": "cat"},
        ],
        "themes": ["friendship"],
        "tone_hint": "gentle",
        "target_length": "medium",
    }
)

PLAN_RESPONSE = json.dumps(
    {
        "title": "The Quiet Garden",
        "setup": "setup text",
        "spark": "spark text",
        "resolution": "resolution text",
        "wind_down": "wind_down text",
    }
)


def _queue(responses: list[str]):
    it = iter(responses)

    def _call(*_args, **_kwargs) -> str:
        return next(it)

    return _call


def test_pipeline_passes_on_first_judge():
    responses = [CAT_RESPONSE, PLAN_RESPONSE, "STORY_v1", _judge_resp(5, True)]
    with patch("llm.call_model", side_effect=_queue(responses)) as mock:
        draft, report, req = generate_story("Alice and her cat Bob")

    assert mock.call_count == 4
    assert report.passing()
    assert draft.iteration == 0
    assert req.category == "animals"
    assert [c.name for c in req.characters] == ["Alice", "Bob"]


def test_pipeline_refines_once_when_judge_fails_then_passes():
    responses = [
        CAT_RESPONSE,
        PLAN_RESPONSE,
        "STORY_v1",
        _judge_resp(2, False, "Soften the chase."),
        "STORY_v2",
        _judge_resp(5, True),
    ]
    with patch("llm.call_model", side_effect=_queue(responses)) as mock:
        draft, report, _ = generate_story("scary cat story")

    assert mock.call_count == 6
    assert report.passing()
    assert draft.iteration == 1
    assert "STORY_v2" in draft.text


def test_pipeline_caps_refinements_at_max():
    """Judge always fails -> pipeline refines exactly MAX_REFINEMENTS times then stops."""
    assert MAX_REFINEMENTS == 2
    responses = [
        CAT_RESPONSE,
        PLAN_RESPONSE,
        "STORY_v1",
        _judge_resp(2, False, "fix"),
        "STORY_v2",
        _judge_resp(2, False, "fix"),
        "STORY_v3",
        _judge_resp(2, False, "fix"),
    ]
    with patch("llm.call_model", side_effect=_queue(responses)) as mock:
        draft, report, _ = generate_story("anything")

    # 1 categorize + 1 plan + 1 tell + 1 initial judge + 2 * (refine + judge) = 8
    assert mock.call_count == 8
    assert not report.passing()
    assert draft.iteration == 2
    assert "STORY_v3" in draft.text


def test_pipeline_emits_events_in_order():
    responses = [CAT_RESPONSE, PLAN_RESPONSE, "STORY", _judge_resp(5, True)]
    events: list[str] = []
    with patch("llm.call_model", side_effect=_queue(responses)):
        generate_story("test", on_event=lambda s, _p: events.append(s))

    assert events.index("categorize_done") < events.index("plan_start")
    assert events.index("plan_done") < events.index("tell_start")
    assert events.index("tell_done") < events.index("judge_start")
    assert events[-1] == "judge_done"


def test_pipeline_emits_refine_events_on_failure():
    responses = [
        CAT_RESPONSE,
        PLAN_RESPONSE,
        "STORY_v1",
        _judge_resp(2, False, "fix"),
        "STORY_v2",
        _judge_resp(5, True),
    ]
    events: list[str] = []
    with patch("llm.call_model", side_effect=_queue(responses)):
        generate_story("test", on_event=lambda s, _p: events.append(s))

    assert "refine_start" in events
    assert "refine_done" in events
    assert events.index("refine_start") > events.index("judge_done")


def test_categorize_falls_back_on_invalid_json():
    with patch("llm.call_model", return_value="not json"):
        req = categorize("anything")
    assert req.category == "friendship"
    assert req.tone_hint == "gentle"
    assert req.characters == []


def test_categorize_clamps_invalid_category_to_default():
    bad = json.dumps(
        {
            "category": "horror",
            "characters": [],
            "themes": [],
            "tone_hint": "spooky",
            "target_length": "epic",
        }
    )
    with patch("llm.call_model", return_value=bad):
        req = categorize("anything")
    assert req.category == "friendship"
    assert req.tone_hint == "gentle"
    assert req.target_length == "medium"


# --- judge-unparseable behavior --------------------------------------------


def test_pipeline_skips_refinement_when_judge_unparseable():
    """Garbage from the judge → ship the draft, don't refine on synthetic
    'unparseable' critiques (which would degrade the story)."""
    responses = [
        CAT_RESPONSE,
        PLAN_RESPONSE,
        "STORY_v1",
        "judge garbage",  # unparseable judge response
    ]
    with patch("llm.call_model", side_effect=_queue(responses)) as mock:
        draft, report, _ = generate_story("anything")
    assert mock.call_count == 4  # no refine attempted
    assert not report.parseable
    assert "STORY_v1" in draft.text


def test_apply_user_tweak_skips_refinement_when_judge_unparseable():
    responses = ["TWEAKED", "judge garbage"]
    with patch("llm.call_model", side_effect=_queue(responses)) as mock:
        new_draft, report = apply_user_tweak(Draft(text="old"), "shorter")
    assert mock.call_count == 2  # tweak + judge only
    assert not report.parseable
    assert "TWEAKED" in new_draft.text


# --- cancellation ----------------------------------------------------------


def test_generate_story_raises_when_cancelled_between_stages():
    """is_cancelled() flips True after the first LLM call → no further calls happen."""
    flag = {"set": False}

    def call_then_set_flag(*_a, **_kw):
        flag["set"] = True
        return CAT_RESPONSE

    with patch("llm.call_model", side_effect=call_then_set_flag) as mock:
        with pytest.raises(PipelineCancelled):
            generate_story("anything", is_cancelled=lambda: flag["set"])
    # Only categorize ran; plan/tell/judge never started.
    assert mock.call_count == 1


# --- apply_user_tweak -------------------------------------------------------


def test_apply_user_tweak_re_judges_and_skips_refine_when_passing():
    responses = ["TWEAKED", _judge_resp(5, True)]
    with patch("llm.call_model", side_effect=_queue(responses)) as mock:
        new_draft, report = apply_user_tweak(Draft(text="old"), "shorter")
    assert mock.call_count == 2  # tweak + judge, no refine
    assert "TWEAKED" in new_draft.text
    assert report.passing()


def test_apply_user_tweak_refines_when_safety_drops():
    responses = [
        "TWEAKED unsafe",
        _judge_with({"safety": 2}, overall=False),
        "REFINED safer",
        _judge_resp(5, True),
    ]
    with patch("llm.call_model", side_effect=_queue(responses)) as mock:
        new_draft, report = apply_user_tweak(Draft(text="old"), "make it scarier")
    assert mock.call_count == 4  # tweak + judge + refine + judge
    assert "REFINED safer" in new_draft.text
    assert report.passing()


def test_apply_user_tweak_does_not_refine_on_non_critical_dim():
    responses = [
        "TWEAKED",
        _judge_with({"narrative_coherence": 2}, overall=False),
    ]
    with patch("llm.call_model", side_effect=_queue(responses)) as mock:
        new_draft, report = apply_user_tweak(Draft(text="old"), "more detail")
    assert mock.call_count == 2  # no refine for non-critical
    assert "TWEAKED" in new_draft.text
    assert not report.passing()


def test_apply_user_tweak_emits_events():
    responses = ["TWEAKED", _judge_resp(5, True)]
    events: list[str] = []
    with patch("llm.call_model", side_effect=_queue(responses)):
        apply_user_tweak(
            Draft(text="old"), "shorter", on_event=lambda s, _p: events.append(s)
        )
    assert "tweak_start" in events
    assert "tweak_done" in events
    assert "judge_done" in events
