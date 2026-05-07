import json
from unittest.mock import patch

from fastapi.testclient import TestClient

import server
from judge import DIMENSIONS


def _judge_resp(score: int = 5, overall: bool = True, fix=None) -> str:
    return json.dumps(
        {
            "scores": {dim: {"score": score, "critique": "ok"} for dim in DIMENSIONS},
            "overall_pass": overall,
            "top_priority_fix": fix,
        }
    )


def _judge_with(score_overrides: dict, default: int = 5, overall: bool = False, fix: str = "x") -> str:
    scores = {dim: {"score": default, "critique": "ok"} for dim in DIMENSIONS}
    for dim, s in score_overrides.items():
        scores[dim] = {"score": s, "critique": "needs work"}
    return json.dumps(
        {"scores": scores, "overall_pass": overall, "top_priority_fix": fix}
    )


CAT = json.dumps(
    {
        "category": "animals",
        "characters": [{"name": "Alice", "kind": "girl"}],
        "themes": ["friendship"],
        "tone_hint": "gentle",
        "target_length": "medium",
    }
)

PLAN = json.dumps(
    {
        "title": "The Quiet Garden",
        "setup": "s",
        "spark": "sp",
        "resolution": "r",
        "wind_down": "w",
    }
)


def _queue(responses):
    it = iter(responses)

    def _call(*_a, **_kw):
        return next(it)

    return _call


def _parse_sse(body: str) -> list[dict]:
    events = []
    for chunk in body.split("\n\n"):
        for line in chunk.split("\n"):
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return events


def test_root_serves_html():
    with TestClient(server.app) as client:
        resp = client.get("/")
    assert resp.status_code == 200
    assert "<html" in resp.text.lower()
    assert "Bedtime" in resp.text


def test_static_assets_served():
    with TestClient(server.app) as client:
        css = client.get("/static/styles.css")
        js = client.get("/static/app.js")
    assert css.status_code == 200
    assert js.status_code == 200
    assert "--accent" in css.text
    assert "streamSSE" in js.text


def test_generate_endpoint_streams_stages_and_story():
    responses = [CAT, PLAN, "STORY_v1", _judge_resp(5, True)]
    with patch("llm.call_model", side_effect=_queue(responses)):
        with TestClient(server.app) as client:
            resp = client.post("/api/generate", json={"input": "test"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse(resp.text)
    types = [e["type"] for e in events]
    stages = [e["stage"] for e in events if e["type"] == "stage"]

    assert "categorize_start" in stages
    assert "judge_done" in stages
    # Stage order is preserved
    assert stages.index("categorize_start") < stages.index("plan_start")
    assert stages.index("tell_done") < stages.index("judge_start")
    # Final story event present
    assert "story" in types
    story_event = next(e for e in events if e["type"] == "story")
    assert "STORY_v1" in story_event["text"]
    assert "reading_time" in story_event
    assert story_event["passed"] is True


def test_generate_endpoint_emits_refine_when_judge_fails():
    responses = [
        CAT, PLAN, "STORY_v1",
        _judge_resp(2, False, "fix"),
        "STORY_v2",
        _judge_resp(5, True),
    ]
    with patch("llm.call_model", side_effect=_queue(responses)):
        with TestClient(server.app) as client:
            resp = client.post("/api/generate", json={"input": "test"})
    events = _parse_sse(resp.text)
    stages = [e["stage"] for e in events if e["type"] == "stage"]
    assert "refine_start" in stages
    assert "refine_done" in stages
    story_event = next(e for e in events if e["type"] == "story")
    assert "STORY_v2" in story_event["text"]
    assert story_event["iterations"] == 1


def test_tweak_endpoint_returns_revised_story():
    """Tweak runs, judge passes → no auto-refine."""
    responses = ["REVISED STORY", _judge_resp(5, True)]
    with patch("llm.call_model", side_effect=_queue(responses)) as mock:
        with TestClient(server.app) as client:
            resp = client.post(
                "/api/tweak",
                json={"story": "old story", "request": "make it shorter"},
            )
    assert resp.status_code == 200
    assert mock.call_count == 2  # tweak + judge, no refine
    events = _parse_sse(resp.text)
    story_event = next(e for e in events if e["type"] == "story")
    assert "REVISED" in story_event["text"]
    assert "reading_time" in story_event
    assert story_event["passed"] is True


def test_tweak_re_judges_and_refines_when_safety_breaks():
    """If a tweak drops safety below threshold, one targeted refinement runs."""
    responses = [
        "TWEAKED unsafe",                                  # 1: tweak
        _judge_with({"safety": 2}, overall=False),         # 2: judge fails on safety
        "REFINED safer",                                   # 3: auto refine
        _judge_resp(5, True),                              # 4: final judge passes
    ]
    with patch("llm.call_model", side_effect=_queue(responses)) as mock:
        with TestClient(server.app) as client:
            resp = client.post(
                "/api/tweak",
                json={"story": "old story", "request": "make it scarier"},
            )
    assert mock.call_count == 4
    events = _parse_sse(resp.text)
    stages = [e["stage"] for e in events if e["type"] == "stage"]
    assert "tweak_done" in stages
    assert "refine_start" in stages
    assert "refine_done" in stages
    story = next(e for e in events if e["type"] == "story")
    assert "REFINED safer" in story["text"]
    assert story["passed"] is True


def test_tweak_re_judges_and_refines_when_ending_calmness_breaks():
    """ending_calmness is the other CRITICAL_DIMENSION — same enforcement."""
    responses = [
        "TWEAKED action ending",
        _judge_with({"ending_calmness": 2}, overall=False),
        "REFINED calmer",
        _judge_resp(5, True),
    ]
    with patch("llm.call_model", side_effect=_queue(responses)) as mock:
        with TestClient(server.app) as client:
            resp = client.post(
                "/api/tweak",
                json={"story": "old story", "request": "more action at the end"},
            )
    assert mock.call_count == 4
    events = _parse_sse(resp.text)
    story = next(e for e in events if e["type"] == "story")
    assert "REFINED calmer" in story["text"]


def test_tweak_does_not_refine_on_non_critical_failure():
    """Non-critical dim failures (e.g., narrative_coherence) don't trigger refine."""
    responses = [
        "TWEAKED",
        _judge_with({"narrative_coherence": 2}, overall=False),
    ]
    with patch("llm.call_model", side_effect=_queue(responses)) as mock:
        with TestClient(server.app) as client:
            resp = client.post(
                "/api/tweak",
                json={"story": "old story", "request": "more detail"},
            )
    assert mock.call_count == 2  # tweak + judge only
    events = _parse_sse(resp.text)
    story = next(e for e in events if e["type"] == "story")
    assert "TWEAKED" in story["text"]
    # Story still ships even though judge didn't pass on a non-critical dim
    assert story["passed"] is False


def test_generate_rejects_empty_input():
    with TestClient(server.app) as client:
        resp = client.post("/api/generate", json={"input": ""})
    assert resp.status_code == 422


def test_tweak_rejects_empty_request():
    with TestClient(server.app) as client:
        resp = client.post("/api/tweak", json={"story": "x", "request": ""})
    assert resp.status_code == 422


def test_generate_returns_generic_error_on_llm_failure():
    """Raw exception details must NOT be echoed to the client."""
    def boom(*_a, **_kw):
        raise RuntimeError("API down: secret-token-xyz")

    with patch("llm.call_model", side_effect=boom):
        with TestClient(server.app) as client:
            resp = client.post("/api/generate", json={"input": "test"})
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    err = next(e for e in events if e["type"] == "error")
    assert "secret-token-xyz" not in err["message"]
    assert "API down" not in err["message"]
    assert err["message"] == server.GENERIC_ERROR


def test_tweak_returns_generic_error_on_llm_failure():
    def boom(*_a, **_kw):
        raise RuntimeError("OpenAI 503")

    with patch("llm.call_model", side_effect=boom):
        with TestClient(server.app) as client:
            resp = client.post(
                "/api/tweak", json={"story": "x", "request": "shorter"}
            )
    events = _parse_sse(resp.text)
    err = next(e for e in events if e["type"] == "error")
    assert "OpenAI 503" not in err["message"]
    assert err["message"] == server.GENERIC_ERROR
