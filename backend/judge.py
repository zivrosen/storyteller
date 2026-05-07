import json

import llm
from models import JudgeReport, DimensionScore
from prompts import JUDGE_PROMPT


DIMENSIONS = [
    "age_appropriateness",
    "bedtime_suitability",
    "narrative_coherence",
    "vocabulary_level",
    "safety",
    "ending_calmness",
    "character_consistency",
]

PASS_THRESHOLD = 4


def parse_judge_response(raw: str) -> JudgeReport:
    """Parse the judge's JSON response into a JudgeReport.

    Tolerates missing or out-of-range fields by defaulting to a 'needs work'
    score (3), which guarantees the story will be refined rather than passed
    through silently. Raises ValueError only on completely invalid JSON.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Judge returned invalid JSON: {e}") from e

    if not isinstance(data, dict):
        raise ValueError("Judge response is not a JSON object")

    scores_raw = data.get("scores")
    if not isinstance(scores_raw, dict):
        scores_raw = {}

    scores: dict[str, DimensionScore] = {}
    for dim in DIMENSIONS:
        entry = scores_raw.get(dim)
        if not isinstance(entry, dict):
            scores[dim] = DimensionScore(score=3, critique="(missing from judge response)")
            continue
        score = entry.get("score")
        # bool is a subclass of int in Python, so reject it explicitly before
        # the int check — `True` would otherwise read as 1.
        if (
            isinstance(score, bool)
            or not isinstance(score, int)
            or not (1 <= score <= 5)
        ):
            score = 3
        critique = entry.get("critique", "")
        if not isinstance(critique, str):
            critique = ""
        scores[dim] = DimensionScore(score=score, critique=critique)

    model_says_pass = bool(data.get("overall_pass", False))
    strict_pass = model_says_pass and all(s.score >= PASS_THRESHOLD for s in scores.values())

    fix = data.get("top_priority_fix")
    if fix is not None and not isinstance(fix, str):
        fix = None

    return JudgeReport(scores=scores, overall_pass=strict_pass, top_priority_fix=fix)


def judge_story(story: str) -> JudgeReport:
    raw = llm.call_model(
        JUDGE_PROMPT.format(story=story),
        max_tokens=1200,
        temperature=0.0,
        json_mode=True,
    )
    try:
        return parse_judge_response(raw)
    except ValueError:
        # JSON-mode parse failures are rare and retrying the same call rarely
        # helps — it just doubles the cost. Return a non-passing, non-parseable
        # report so the pipeline ships the current draft (refining against
        # synthetic 'unparseable' critiques tends to degrade the story).
        return JudgeReport(
            scores={
                dim: DimensionScore(3, "Judge response unparseable.")
                for dim in DIMENSIONS
            },
            overall_pass=False,
            top_priority_fix=None,
            parseable=False,
        )
