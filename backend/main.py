import sys

from models import Draft
from pipeline import generate_story, apply_user_tweak
from utils import estimate_reading_time


STAGE_LABELS = {
    "categorize_start": "Reading your request...",
    "categorize_done": "Got it.",
    "plan_start": "Sketching the story arc...",
    "plan_done": "Outline ready.",
    "tell_start": "Writing the story...",
    "tell_done": "First draft done.",
    "judge_start": "Asking the editor for feedback...",
    "judge_done": "Editor reviewed",
    "refine_start": "Polishing based on feedback...",
    "refine_done": "Revision done",
    "tweak_start": "Applying your tweak...",
    "tweak_done": "Tweak applied.",
}


def _on_event(stage: str, payload: dict) -> None:
    label = STAGE_LABELS.get(stage)
    if not label:
        return
    suffix = ""
    if stage == "judge_done":
        suffix = " (passed)" if payload.get("pass") else " (needs polish)"
    elif stage == "refine_done":
        suffix = " (passed)" if payload.get("pass") else " (still polishing)"
    print(f"  - {label}{suffix}", file=sys.stderr)


def _print_story(draft: Draft) -> None:
    print()
    print(draft.text)
    print()
    print(f"~ approx. read-aloud time: {estimate_reading_time(draft.text)} ~")
    print()


def main() -> None:
    try:
        user_input = input("What kind of story do you want to hear? ").strip()
    except EOFError:
        user_input = ""
    if not user_input:
        print("No request given. Goodnight!")
        return

    draft, _report, _req = generate_story(user_input, on_event=_on_event)
    _print_story(draft)

    while True:
        try:
            choice = input(
                "Anything to change? (Enter to accept, or describe a tweak): "
            ).strip()
        except EOFError:
            break
        if not choice:
            print("Sweet dreams!")
            break
        draft, report = apply_user_tweak(draft, choice, on_event=_on_event)
        if not report.passing():
            print(
                "  - Heads up: the editor flagged the tweaked version.",
                file=sys.stderr,
            )
        _print_story(draft)


if __name__ == "__main__":
    main()
