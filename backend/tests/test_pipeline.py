import json
from unittest.mock import patch

import pytest

from pipeline import generate_story, MAX_REFINEMENTS, categorize
from judge import DIMENSIONS


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
