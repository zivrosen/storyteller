import json
from unittest.mock import patch

import pytest

from judge import parse_judge_response, judge_story, DIMENSIONS


def _full_scores(score: int = 5, critique: str = "Looks good.") -> dict:
    return {dim: {"score": score, "critique": critique} for dim in DIMENSIONS}


def test_parse_perfect_response():
    raw = json.dumps(
        {"scores": _full_scores(5), "overall_pass": True, "top_priority_fix": None}
    )
    report = parse_judge_response(raw)
    assert report.passing()
    assert report.top_priority_fix is None
    assert all(s.score == 5 for s in report.scores.values())


def test_parser_overrides_lying_overall_pass():
    """Model claims pass=true but a dimension scored 3 -> parser must mark fail."""
    scores = _full_scores(5)
    scores["safety"] = {"score": 3, "critique": "Brief mention of monster."}
    raw = json.dumps(
        {"scores": scores, "overall_pass": True, "top_priority_fix": "Soften the monster."}
    )
    report = parse_judge_response(raw)
    assert not report.passing()
    assert report.top_priority_fix == "Soften the monster."


def test_parse_invalid_json_raises():
    with pytest.raises(ValueError):
        parse_judge_response("this is not json")


def test_parse_non_object_root_raises():
    with pytest.raises(ValueError):
        parse_judge_response('["not", "an object"]')


def test_parse_missing_dimension_defaults_to_three():
    scores = _full_scores(5)
    del scores["safety"]
    raw = json.dumps(
        {"scores": scores, "overall_pass": True, "top_priority_fix": None}
    )
    report = parse_judge_response(raw)
    assert report.scores["safety"].score == 3
    assert not report.passing()


def test_parse_out_of_range_score_falls_back():
    scores = _full_scores(5)
    scores["age_appropriateness"] = {"score": 99, "critique": "x"}
    raw = json.dumps(
        {"scores": scores, "overall_pass": True, "top_priority_fix": None}
    )
    report = parse_judge_response(raw)
    assert report.scores["age_appropriateness"].score == 3


def test_parse_missing_scores_section_yields_all_threes():
    raw = json.dumps({"overall_pass": True, "top_priority_fix": None})
    report = parse_judge_response(raw)
    assert all(s.score == 3 for s in report.scores.values())
    assert not report.passing()


def test_judge_story_recovers_from_one_bad_response():
    """First call returns garbage; second call returns valid JSON. Should succeed."""
    good = json.dumps(
        {"scores": _full_scores(5), "overall_pass": True, "top_priority_fix": None}
    )
    responses = iter(["not json", good])
    with patch("llm.call_model", side_effect=lambda *a, **kw: next(responses)) as mock:
        report = judge_story("a calming story")
    assert mock.call_count == 2
    assert report.passing()


def test_judge_story_returns_failing_report_after_two_bad_responses():
    """Both retries produce bad JSON -> safe failing report, not an exception."""
    responses = iter(["not json", "still not json"])
    with patch("llm.call_model", side_effect=lambda *a, **kw: next(responses)):
        report = judge_story("a calming story")
    assert not report.passing()
    assert report.top_priority_fix is not None
