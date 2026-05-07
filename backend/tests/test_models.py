from models import StoryRequest, Character, StoryPlan, Draft


def test_story_request_defaults():
    r = StoryRequest(user_input="hello")
    assert r.category == "friendship"
    assert r.tone_hint == "gentle"
    assert r.target_length == "medium"
    assert r.characters == []
    assert r.themes == []


def test_character_round_trip():
    c = Character(name="Alice", kind="girl")
    assert c.name == "Alice"
    assert c.kind == "girl"


def test_story_plan_fields():
    p = StoryPlan(title="t", setup="s", spark="sp", resolution="r", wind_down="w")
    assert p.title == "t"
    assert p.wind_down == "w"


def test_draft_iteration_default():
    d = Draft(text="hello")
    assert d.iteration == 0


def test_passing_report(passing_report):
    assert passing_report.passing()


def test_failing_report(failing_report):
    assert not failing_report.passing()


def test_format_critique_orders_lowest_first(failing_report):
    out = failing_report.format_critique()
    bedtime_idx = out.find("bedtime_suitability")
    age_idx = out.find("age_appropriateness")
    assert bedtime_idx != -1 and age_idx != -1
    assert bedtime_idx < age_idx
