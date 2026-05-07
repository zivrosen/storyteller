import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from models import JudgeReport, DimensionScore


@pytest.fixture
def passing_report() -> JudgeReport:
    return JudgeReport(
        scores={
            "age_appropriateness": DimensionScore(5, "Looks good."),
            "bedtime_suitability": DimensionScore(5, "Looks good."),
            "narrative_coherence": DimensionScore(5, "Looks good."),
            "vocabulary_level": DimensionScore(5, "Looks good."),
            "safety": DimensionScore(5, "Looks good."),
            "ending_calmness": DimensionScore(5, "Looks good."),
            "character_consistency": DimensionScore(5, "Looks good."),
        },
        overall_pass=True,
        top_priority_fix=None,
    )


@pytest.fixture
def failing_report() -> JudgeReport:
    return JudgeReport(
        scores={
            "age_appropriateness": DimensionScore(4, "Looks good."),
            "bedtime_suitability": DimensionScore(2, "Too exciting at the end."),
            "narrative_coherence": DimensionScore(4, "Looks good."),
            "vocabulary_level": DimensionScore(4, "Looks good."),
            "safety": DimensionScore(4, "Looks good."),
            "ending_calmness": DimensionScore(2, "Last paragraph mentions a chase."),
            "character_consistency": DimensionScore(4, "Looks good."),
        },
        overall_pass=False,
        top_priority_fix="Replace the chase scene at the end with a quieter wind-down.",
    )
