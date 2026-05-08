#!/usr/bin/env python3
"""Run the bedtime pipeline against a representative prompt set and print a
per-dimension quality summary.

This hits the real OpenAI API (about 4-7 calls per prompt). With the default
10-prompt suite it costs roughly $0.05 and takes 3-5 minutes total.

    python evals/run_evals.py
    python evals/run_evals.py --limit 3
    python evals/run_evals.py --json evals/last_run.json
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

# Make the parent backend/ dir importable when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from judge import DIMENSIONS  # noqa: E402
from pipeline import generate_story  # noqa: E402


HERE = Path(__file__).resolve().parent
DEFAULT_PROMPTS = HERE / "prompts.txt"


def load_prompts(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def run_one(prompt: str) -> dict:
    t0 = time.monotonic()
    draft, report, req = generate_story(prompt)
    elapsed = time.monotonic() - t0
    return {
        "prompt": prompt,
        "category": req.category,
        "characters": [c.name for c in req.characters],
        "passed": report.passing(),
        "parseable": report.parseable,
        "iterations": draft.iteration,
        "elapsed_s": round(elapsed, 1),
        "scores": {dim: report.scores[dim].score for dim in DIMENSIONS},
        "story_words": len(draft.text.split()),
    }


def aggregate(results: list[dict]) -> dict:
    successes = [r for r in results if "error" not in r]
    if not successes:
        return {"n": len(results), "n_errors": len(results)}
    return {
        "n": len(results),
        "n_errors": len(results) - len(successes),
        "pass_rate": sum(1 for r in successes if r["passed"]) / len(successes),
        "avg_iterations": round(
            statistics.mean(r["iterations"] for r in successes), 2
        ),
        "avg_elapsed_s": round(
            statistics.mean(r["elapsed_s"] for r in successes), 1
        ),
        "median_elapsed_s": round(
            statistics.median(r["elapsed_s"] for r in successes), 1
        ),
        "avg_words": round(statistics.mean(r["story_words"] for r in successes)),
        "avg_score_by_dim": {
            dim: round(
                statistics.mean(r["scores"][dim] for r in successes), 2
            )
            for dim in DIMENSIONS
        },
    }


def _truncate(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def print_summary(results: list[dict], agg: dict) -> None:
    print()
    print(
        f"{'Prompt':<58} {'Cat':<11} {'Pass':<5} {'Iter':<5} {'Time':<6}"
    )
    print("-" * 86)
    for r in results:
        if "error" in r:
            print(f"{_truncate(r['prompt'], 58):<58}  ERROR: {r['error']}")
            continue
        print(
            f"{_truncate(r['prompt'], 58):<58} "
            f"{r['category'][:10]:<11} "
            f"{('PASS' if r['passed'] else 'FAIL'):<5} "
            f"{r['iterations']:<5} "
            f"{r['elapsed_s']}s"
        )
    print()
    if "pass_rate" not in agg:
        print(f"All {agg['n']} runs errored.")
        return

    print(f"Pass rate:        {agg['pass_rate']:.0%}  ({agg['n']} prompts, "
          f"{agg['n_errors']} errors)")
    print(f"Avg iterations:   {agg['avg_iterations']}")
    print(f"Avg time:         {agg['avg_elapsed_s']}s  "
          f"(median {agg['median_elapsed_s']}s)")
    print(f"Avg story length: {agg['avg_words']} words")
    print()
    print("Avg score by dimension (1-5):")
    for dim, score in agg["avg_score_by_dim"].items():
        # 4-char-per-point bar: 5.00 → 20 chars filled.
        filled = int(round(score * 4))
        bar = "█" * filled + "░" * (20 - filled)
        print(f"  {dim:<22} {score:.2f}  {bar}")
    print()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--prompts", default=str(DEFAULT_PROMPTS),
                    help="Path to prompts file (one prompt per line).")
    ap.add_argument("--limit", type=int,
                    help="Run only the first N prompts (for cheap dev runs).")
    ap.add_argument("--json",
                    help="Also write raw results + summary as JSON to this path.")
    args = ap.parse_args()

    prompts = load_prompts(Path(args.prompts))
    if args.limit:
        prompts = prompts[: args.limit]

    print(f"Running {len(prompts)} prompts through the pipeline…",
          file=sys.stderr)
    results: list[dict] = []
    for i, prompt in enumerate(prompts, 1):
        print(f"  [{i}/{len(prompts)}] {_truncate(prompt, 70)}",
              file=sys.stderr)
        try:
            results.append(run_one(prompt))
        except Exception as e:  # noqa: BLE001 — broad catch is intentional here
            print(f"    failed: {e}", file=sys.stderr)
            results.append({"prompt": prompt, "error": str(e)})

    agg = aggregate(results)
    print_summary(results, agg)

    if args.json:
        Path(args.json).write_text(
            json.dumps({"results": results, "summary": agg}, indent=2)
        )
        print(f"Raw results saved to {args.json}", file=sys.stderr)


if __name__ == "__main__":
    main()
