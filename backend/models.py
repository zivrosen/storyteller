from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Character:
    name: str
    kind: str


@dataclass
class StoryRequest:
    user_input: str
    category: str = "friendship"
    characters: list[Character] = field(default_factory=list)
    themes: list[str] = field(default_factory=list)
    tone_hint: str = "gentle"
    target_length: str = "medium"


@dataclass
class StoryPlan:
    title: str
    setup: str
    spark: str
    resolution: str
    wind_down: str


@dataclass
class Draft:
    text: str
    iteration: int = 0


@dataclass
class DimensionScore:
    score: int
    critique: str


@dataclass
class JudgeReport:
    scores: dict[str, DimensionScore]
    overall_pass: bool
    top_priority_fix: Optional[str]
    # False when the judge response couldn't be parsed; consumers should treat
    # the report as informational only and skip refinement (refining without a
    # real critique tends to make stories worse, not better).
    parseable: bool = True

    def passing(self) -> bool:
        if not self.scores:
            return False
        return self.overall_pass and all(s.score >= 4 for s in self.scores.values())

    def format_critique(self) -> str:
        items = sorted(self.scores.items(), key=lambda kv: kv[1].score)
        return "\n".join(
            f"- {dim} (score {ds.score}/5): {ds.critique}" for dim, ds in items
        )
