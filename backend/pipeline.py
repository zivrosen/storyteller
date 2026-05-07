import json
from typing import Callable, Optional

import llm
from models import StoryRequest, StoryPlan, Draft, JudgeReport, Character
from prompts import (
    CATEGORIZER_PROMPT,
    PLANNER_PROMPT,
    STORYTELLER_PROMPT,
    REFINER_PROMPT,
    USER_TWEAK_PROMPT,
)
from judge import judge_story, PASS_THRESHOLD
from utils import format_characters, target_words


VALID_CATEGORIES = {"adventure", "animals", "fairy_tale", "friendship", "silly", "calming"}
VALID_TONES = {"gentle", "adventurous", "whimsical", "cozy"}
VALID_LENGTHS = {"short", "medium", "long"}

MAX_REFINEMENTS = 2

# Judge dimensions we will *always* fix after a user tweak, even if the tweak
# was the user's explicit request — bedtime safety overrides user intent here.
CRITICAL_DIMENSIONS = ("safety", "ending_calmness")


class PipelineCancelled(Exception):
    """Raised at pipeline checkpoints when the caller signals cancellation.

    The pipeline can't interrupt an in-flight LLM call, but it stops *starting*
    new ones once the cancel flag is set, which is what saves API spend when a
    web client disconnects mid-generation.
    """


CancelCheck = Callable[[], bool]
EventHandler = Callable[[str, dict], None]


def _emit(on_event: Optional[EventHandler], stage: str, payload: dict) -> None:
    if on_event:
        on_event(stage, payload)


def _check(is_cancelled: Optional[CancelCheck]) -> None:
    if is_cancelled and is_cancelled():
        raise PipelineCancelled()


def categorize(user_input: str) -> StoryRequest:
    raw = llm.call_model(
        CATEGORIZER_PROMPT.format(user_input=user_input),
        max_tokens=400,
        temperature=0.0,
        json_mode=True,
    )
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return StoryRequest(user_input=user_input)

    if not isinstance(data, dict):
        return StoryRequest(user_input=user_input)

    characters: list[Character] = []
    chars_raw = data.get("characters") or []
    if isinstance(chars_raw, list):
        for c in chars_raw:
            if isinstance(c, dict) and "name" in c:
                characters.append(
                    Character(name=str(c["name"]), kind=str(c.get("kind", "character")))
                )

    category = data.get("category", "friendship")
    if category not in VALID_CATEGORIES:
        category = "friendship"

    tone = data.get("tone_hint", "gentle")
    if tone not in VALID_TONES:
        tone = "gentle"

    length = data.get("target_length", "medium")
    if length not in VALID_LENGTHS:
        length = "medium"

    themes_raw = data.get("themes") or []
    themes = [str(t) for t in themes_raw][:3] if isinstance(themes_raw, list) else []

    return StoryRequest(
        user_input=user_input,
        category=category,
        characters=characters,
        themes=themes,
        tone_hint=tone,
        target_length=length,
    )


def plan_story(req: StoryRequest) -> StoryPlan:
    raw = llm.call_model(
        PLANNER_PROMPT.format(
            category=req.category,
            characters=format_characters(req.characters),
            themes=", ".join(req.themes) or "(none specified)",
            tone_hint=req.tone_hint,
            user_input=req.user_input,
        ),
        max_tokens=700,
        temperature=0.4,
        json_mode=True,
    )
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    return StoryPlan(
        title=str(data.get("title") or "A Bedtime Story"),
        setup=str(data.get("setup") or ""),
        spark=str(data.get("spark") or ""),
        resolution=str(data.get("resolution") or ""),
        wind_down=str(data.get("wind_down") or ""),
    )


def tell_story(req: StoryRequest, plan: StoryPlan) -> Draft:
    text = llm.call_model(
        STORYTELLER_PROMPT.format(
            target_words=target_words(req.target_length),
            tone_hint=req.tone_hint,
            title=plan.title,
            setup=plan.setup,
            spark=plan.spark,
            resolution=plan.resolution,
            wind_down=plan.wind_down,
        ),
        max_tokens=1800,
        temperature=0.8,
    )
    return Draft(text=text.strip(), iteration=0)


def refine_story(draft: Draft, report: JudgeReport) -> Draft:
    text = llm.call_model(
        REFINER_PROMPT.format(
            critique_block=report.format_critique(),
            draft=draft.text,
        ),
        max_tokens=1800,
        temperature=0.6,
    )
    return Draft(text=text.strip(), iteration=draft.iteration + 1)


def generate_story(
    user_input: str,
    on_event: Optional[EventHandler] = None,
    max_refinements: int = MAX_REFINEMENTS,
    is_cancelled: Optional[CancelCheck] = None,
) -> tuple[Draft, JudgeReport, StoryRequest]:
    """Run the full pipeline. Returns (final draft, last judge report, parsed request).

    `is_cancelled` is checked between stages; if it returns True, the pipeline
    raises `PipelineCancelled` rather than starting another LLM call.
    """
    _emit(on_event, "categorize_start", {"input": user_input})
    req = categorize(user_input)
    _emit(on_event, "categorize_done",
          {"category": req.category, "characters": [c.name for c in req.characters]})
    _check(is_cancelled)

    _emit(on_event, "plan_start", {})
    plan = plan_story(req)
    _emit(on_event, "plan_done", {"title": plan.title})
    _check(is_cancelled)

    _emit(on_event, "tell_start", {})
    draft = tell_story(req, plan)
    _emit(on_event, "tell_done", {"iteration": draft.iteration})
    _check(is_cancelled)

    _emit(on_event, "judge_start", {})
    report = judge_story(draft.text)
    passed = report.passing()
    _emit(on_event, "judge_done", {"pass": passed, "iteration": draft.iteration})

    refinements = 0
    # Only refine when the judge actually returned a usable critique.
    while not passed and report.parseable and refinements < max_refinements:
        _check(is_cancelled)
        _emit(on_event, "refine_start", {"iteration": refinements + 1})
        draft = refine_story(draft, report)
        report = judge_story(draft.text)
        passed = report.passing()
        refinements += 1
        _emit(on_event, "refine_done", {"iteration": refinements, "pass": passed})

    return draft, report, req


def apply_user_tweak(
    draft: Draft,
    user_request: str,
    on_event: Optional[EventHandler] = None,
    is_cancelled: Optional[CancelCheck] = None,
) -> tuple[Draft, JudgeReport]:
    """Apply a user tweak, then re-judge.

    Tweaks bypass the auto-refinement loop's editor critique, so a request
    like "make it scarier" can silently break safety or the wind-down ending.
    We always re-run the judge afterwards. If a CRITICAL_DIMENSION (safety or
    ending_calmness) drops below threshold, we run one targeted refinement —
    bedtime safety beats user intent.
    """
    _emit(on_event, "tweak_start", {})
    text = llm.call_model(
        USER_TWEAK_PROMPT.format(user_request=user_request, draft=draft.text),
        max_tokens=1800,
        temperature=0.6,
    )
    new_draft = Draft(text=text.strip(), iteration=draft.iteration + 1)
    _emit(on_event, "tweak_done", {"iteration": new_draft.iteration})
    _check(is_cancelled)

    _emit(on_event, "judge_start", {})
    report = judge_story(new_draft.text)
    _emit(on_event, "judge_done",
          {"pass": report.passing(), "iteration": new_draft.iteration})

    failed_critical = any(
        (s := report.scores.get(dim)) is not None and s.score < PASS_THRESHOLD
        for dim in CRITICAL_DIMENSIONS
    )
    # Skip the safety-refine when the judge couldn't be parsed — synthetic
    # 'unparseable' critiques don't give the refiner anything to act on.
    if failed_critical and report.parseable:
        _check(is_cancelled)
        _emit(on_event, "refine_start", {"iteration": 1})
        new_draft = refine_story(new_draft, report)
        report = judge_story(new_draft.text)
        _emit(on_event, "refine_done",
              {"iteration": 1, "pass": report.passing()})

    return new_draft, report
