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
from judge import judge_story
from utils import format_characters, target_words


VALID_CATEGORIES = {"adventure", "animals", "fairy_tale", "friendship", "silly", "calming"}
VALID_TONES = {"gentle", "adventurous", "whimsical", "cozy"}
VALID_LENGTHS = {"short", "medium", "long"}

MAX_REFINEMENTS = 2


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


def apply_user_tweak(draft: Draft, user_request: str) -> Draft:
    text = llm.call_model(
        USER_TWEAK_PROMPT.format(user_request=user_request, draft=draft.text),
        max_tokens=1800,
        temperature=0.6,
    )
    return Draft(text=text.strip(), iteration=draft.iteration + 1)


EventHandler = Callable[[str, dict], None]


def generate_story(
    user_input: str,
    on_event: Optional[EventHandler] = None,
    max_refinements: int = MAX_REFINEMENTS,
) -> tuple[Draft, JudgeReport, StoryRequest]:
    """Run the full pipeline. Returns (final draft, last judge report, parsed request)."""

    def emit(stage: str, payload: dict) -> None:
        if on_event:
            on_event(stage, payload)

    emit("categorize_start", {"input": user_input})
    req = categorize(user_input)
    emit(
        "categorize_done",
        {"category": req.category, "characters": [c.name for c in req.characters]},
    )

    emit("plan_start", {})
    plan = plan_story(req)
    emit("plan_done", {"title": plan.title})

    emit("tell_start", {})
    draft = tell_story(req, plan)
    emit("tell_done", {"iteration": draft.iteration})

    emit("judge_start", {})
    report = judge_story(draft.text)
    emit("judge_done", {"pass": report.passing(), "iteration": draft.iteration})

    refinements = 0
    while not report.passing() and refinements < max_refinements:
        emit("refine_start", {"iteration": refinements + 1})
        draft = refine_story(draft, report)
        report = judge_story(draft.text)
        refinements += 1
        emit("refine_done", {"iteration": refinements, "pass": report.passing()})

    return draft, report, req
