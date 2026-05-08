# Bedtime Story Generator

A multi-stage prompting pipeline that turns a one-line request
("a story about Alice and her cat Bob") into a calming,
age-appropriate bedtime story for ages 5-10. Includes an LLM
judge with a refinement loop and an interactive feedback step.

Built on `gpt-3.5-turbo` (fixed by assignment requirement).

<p align="center">
  <img src="docs/demo.gif" alt="Live demo: typing a request, the progress timeline lighting up stage-by-stage, and the story rendering at the end." width="640" />
</p>

## Example

**Prompt:** *A story about Alice and her cat Bob, who finds a quiet star in the garden.*

> ### Alice and Bob's Quiet Star
>
> In a cozy little house, Alice and her cat Bob lived together as best friends. They spent their days exploring the garden and playing in the sun.
>
> One evening, as they were strolling through the garden, Bob suddenly stopped and stared up at the sky. Alice followed his gaze and saw a quiet star twinkling in the distance, filling her with wonder.
>
> Together, Alice and Bob decided to sit under the quiet star and enjoy its peaceful light. They talked about their day and shared stories until they felt warm and content.
>
> As the night grew darker and the quiet star shone brighter, Alice and Bob curled up together, feeling safe and sleepy. The garden whispered lullabies as they drifted off into dreams.

*Auto-categorised as `friendship` · ~52s read-aloud · passed the editor on the first try (no refinements needed). Generated end-to-end in ~12s with four LLM calls (categorise → plan → tell → judge).*

## Project layout

```
backend/    Python pipeline, FastAPI server, tests
frontend/   Single-page UI (index.html, styles.css, app.js)
```

All commands below assume you're at the project root.

## Setup

```bash
pip install -r backend/requirements.txt
cp .env.example .env
# edit .env with your OPENAI_API_KEY
```

The app loads `.env` automatically via `python-dotenv`. Either project root
or `backend/` works — `find_dotenv` walks up from `backend/llm.py`.

## Run — Web (recommended)

```bash
python backend/server.py
# then open http://127.0.0.1:8000
```

Single-page app with a live progress timeline that lights up as each
pipeline stage finishes (categorize → plan → write → judge → polish).
Story renders with title, body, and a read-aloud time chip. A tweak
input below lets you say *"make it shorter"*, *"more about Bob"*, or
*"less scary"* and the story re-renders in place.

Streaming is implemented with Server-Sent Events; the pipeline's
existing `on_event` callback feeds straight into the SSE queue. The
FastAPI server mounts `frontend/` at `/static` and serves `index.html`
at `/`.

## Run — CLI

```bash
python backend/main.py
```

## Test

```bash
cd backend && pytest
```

All tests mock `llm.call_model`, so no real API calls are made.

Coverage:

- `test_models.py` — dataclass defaults, strict-pass logic, critique ordering
- `test_utils.py` — reading-time estimate, length mapping, character formatting
- `test_prompts.py` — every template renders with required placeholders
- `test_judge.py` — JSON parsing, missing/out-of-range fields, override-the-lying-model, retry-on-bad-JSON, safe failing report after 2 bad responses
- `test_pipeline.py` — passes on first judge, refines on failure, caps at 2 refinements, event ordering, categorizer fallbacks
- `test_server.py` — root + static assets, SSE event streaming for `/api/generate` and `/api/tweak`, refine-on-fail in the stream, input validation, LLM error surfaced as event

## Quality eval

Unit tests verify mechanics. An offline eval suite verifies *output
quality* — the thing that actually matters to the kid being read to.

### What it measures

For each prompt in `backend/evals/prompts.txt`, the runner executes the
full pipeline (categorise → plan → tell → judge → optional refine) and
records:

| Metric | Why it matters |
|---|---|
| Detected category + named characters | Catches categoriser drift |
| Pass / fail | Headline number — does the editor sign off? |
| Per-dimension scores (1–5) | The seven rubric axes; reveals *which* axis regressed |
| Refinement iterations (0–2) | A spike means the storyteller's first drafts got weaker |
| End-to-end wall-clock time | Tracks latency budget |
| Story length in words | Detects target-length drift |

The judge dimensions are the same seven used in-loop during generation:
`age_appropriateness`, `bedtime_suitability`, `narrative_coherence`,
`vocabulary_level`, `safety`, `ending_calmness`, `character_consistency`.

### The prompt set

Ten prompts chosen to stress every branch the pipeline cares about:

- **Coverage** — all six categories (animals, fairy_tale, friendship,
  silly, adventure, calming).
- **Variety** — solo vs. group, named vs. unnamed characters, short
  vs. long prompts, explicit vs. implicit themes.
- **Fallbacks** — one extremely terse prompt (`A story.`) verifies the
  categoriser's defaults kick in instead of silently failing.
- **Red team** — one adversarial prompt (`monsters chasing the heroes
  and a big scary fight`) verifies that `safety` and `ending_calmness`
  still hold under pressure. The judge should pull it back into
  bedtime range; if it doesn't, refine should.

Edit `backend/evals/prompts.txt` to add cases. Lines starting with `#`
are ignored.

### Running it

```bash
cd backend
python evals/run_evals.py                                  # full suite
python evals/run_evals.py --limit 3                        # cheap dev run
python evals/run_evals.py --json evals/last_run.json       # snapshot
```

Cost and time at full run: roughly **$0.05** and **3–5 minutes** on
`gpt-3.5-turbo`. Sequential by design — it's a quality probe, not a load
test.

### Sample output

```
Prompt                                                     Cat         Pass  Iter  Time
--------------------------------------------------------------------------------------
A story about Alice and her cat Bob, who finds a quiet s…  friendship  PASS  0     12.4s
A bunny who learns to share carrots with new friends in …  animals     PASS  0     14.1s
A short bedtime story about a little dragon who cannot f…  calming     PASS  1     22.7s
…

Pass rate:        9/10
Avg iterations:   0.6
Avg time:         15.2s  (median 13.9s)
Avg story length: 410 words

Avg score by dimension (1-5):
  age_appropriateness    4.6  ██████████████████░░
  bedtime_suitability    4.5  ██████████████████░░
  narrative_coherence    4.4  █████████████████░░░
  vocabulary_level       4.7  ███████████████████░
  safety                 4.3  █████████████████░░░
  ending_calmness        4.2  ████████████████░░░░
  character_consistency  4.5  ██████████████████░░
```

The bar chart is what makes regressions easy to spot: if a prompt edit
drops `ending_calmness` from 4.2 to 3.6, you see it immediately on the
next run, before users do.

### Why this matters

The judge runs in-loop during a single generation, which makes *that
story* safer. The eval suite runs the same judge across a representative
slice of inputs and aggregates — which tells you whether a prompt or
pipeline change improved or regressed the system *as a whole*.

It's the cheapest insurance against the most common LLM-product failure
mode: shipping a prompt edit that quietly tanks one rubric axis while
the developer was looking at a different one.

A few extensions I would add with more time: a separate "regression"
mode that diffs the latest run against `last_run.json` and exits non-zero
on a >0.3 drop in any dimension (so it can run in CI), and a
human-rated subset to calibrate the LLM judge's scores against real
parents' opinions.

## Architecture

```mermaid
flowchart TD
    User([User Request<br/>web or CLI])

    subgraph Pipeline[Story Pipeline]
        direction TB
        Cat["1 - Categorizer<br/>(LLM, JSON mode)<br/><br/>category, characters,<br/>themes, tone, length"]
        Plan["2 - Story Planner<br/>(LLM, JSON mode)<br/><br/>4-beat outline:<br/>SETUP, SPARK,<br/>RESOLUTION, WIND_DOWN"]
        Tell["3 - Storyteller<br/>(LLM, prose)<br/><br/>target words, tone,<br/>banned-content list,<br/>wind-down required"]
        Judge{{"4 - Judge<br/>(LLM, JSON mode)<br/><br/>7-dim rubric<br/>pass = all >= 4/5"}}
        Refine["5 - Refiner<br/>(LLM, targeted edits)<br/><br/>not a full rewrite<br/>max 2 iterations"]

        Cat -- StoryRequest --> Plan
        Plan -- StoryPlan --> Tell
        Tell -- Draft --> Judge
        Judge -- fail --> Refine
        Refine -- new Draft --> Judge
    end

    Display[/"Display Story<br/>+ reading time"/]
    Tweak["6 - User Feedback<br/>Enter = accept<br/>text = User Tweak prompt"]
    UserTweak["User Tweak<br/>(LLM, targeted edits<br/>from free-form request)<br/><br/>re-judge always;<br/>force-refine if safety<br/>or wind-down breaks"]

    User --> Cat
    Judge -- pass --> Display
    Display --> Tweak
    Tweak -- text --> UserTweak
    UserTweak --> Display
    Tweak -- Enter --> Done([Sweet dreams])

    classDef llm fill:#e7f0ff,stroke:#3b6ec5,color:#0b2545
    classDef io fill:#fff7e6,stroke:#c98a1a,color:#4a2f00
    classDef done fill:#e9f7ec,stroke:#3a8a4f,color:#1c4a2c
    class Cat,Plan,Tell,Judge,Refine,UserTweak llm
    class User,Display,Tweak io
    class Done done
```

Legend: blue = LLM call · amber = user-facing I/O · green = terminal state.
Full diagram (with extended commentary and an ASCII version) lives in
[`diagram.md`](./diagram.md).

## Design

The pipeline has six stages:

1. **Categorize** — classify the request into one of six story types
   (`adventure`, `animals`, `fairy_tale`, `friendship`, `silly`,
   `calming`) and extract named characters, themes, and a tone hint.
2. **Plan** — build a 4-beat outline: SETUP → SPARK → RESOLUTION →
   WIND_DOWN. The 4th beat is enforced as a calming wind-down — this
   is the bedtime-specific differentiator.
3. **Tell** — write the full story from the outline with
   category-tailored tone, a banned-content list, and a target word
   count derived from `target_length`.
4. **Judge** — score across 7 dimensions (`age_appropriateness`,
   `bedtime_suitability`, `narrative_coherence`, `vocabulary_level`,
   `safety`, `ending_calmness`, `character_consistency`). All must
   score ≥ 4/5 to pass.
5. **Refine** — if the judge fails, the storyteller revises with
   targeted edits driven by the per-dimension critique. Capped at
   2 refinements.
6. **User feedback** — interactive: accept the story, or describe a
   tweak that runs through a dedicated user-tweak prompt.

### Why multi-stage with `gpt-3.5-turbo`?

We're constrained to `gpt-3.5-turbo` (per the assignment).
Single-shot prompting on this model yields uneven structure and weak
endings — exactly the things that matter most for bedtime. Splitting
into categorize → plan → tell → judge gives each call a smaller,
well-scoped job, which the model handles more reliably than one
large request.

### Why `ending_calmness` as its own judge dimension?

Generic kid-story prompts end with energy ("...and then they all
cheered!"). For bedtime, the last paragraph needs to slow down and
point toward sleep. Making this a stand-alone judge dimension means
the refinement loop has a specific lever to pull when the ending
drifts off-target.

### Why cap refinements at 2?

Empirically, one refinement clears the threshold most of the time. A
second is occasionally needed. Beyond two, marginal quality gains are
small relative to latency and API cost.

## What I'd build next

- **TTS playback** (OpenAI TTS) so the story can actually be read aloud at
  bedtime — with the playback rate slowing slightly during the wind-down
  paragraph to match the pacing intent.
- **Per-child profile saved across sessions**: the listener's name,
  favourite characters, themes that worked well, themes to avoid. A second
  story for the same child should feel like a continuation, not a
  cold-start.
- **Streaming storyteller** so the prose appears word-by-word as it's
  written, instead of waiting for the full draft to render. The pipeline
  already streams stage events; only the storyteller call is currently
  buffered.
- **Pacing-specific judge dimension** that measures sentence-length
  tapering toward the end. Right now `ending_calmness` is one rubric line;
  a dedicated structural metric would let the refiner target rhythm
  directly, not just vibe.
- **Paragraph-level "tap to regenerate"** in the web UI so a parent can
  patch one section without re-running the whole story.

## Files

```
backend/
  main.py          — CLI entry point
  server.py        — FastAPI web app (SSE streaming for live progress)
  pipeline.py      — categorize → plan → tell → judge → refine orchestration
  prompts.py       — all prompt templates, centralized
  judge.py         — judge invocation, JSON parsing, threshold logic
  llm.py           — OpenAI client wrapper (gpt-3.5-turbo, fixed) + dotenv
  models.py        — typed dataclasses
  utils.py         — reading-time, character formatting, length mapping
  requirements.txt
  tests/           — pytest suite (LLM mocked at llm.call_model boundary)
  evals/           — end-to-end quality eval (real OpenAI calls)
frontend/
  index.html       — single-page UI
  styles.css       — calm bedtime palette + responsive layout
  app.js           — SSE streaming client + story renderer + tweak handler
docs/
  demo.gif         — 21s recording of the live UI
scripts/
  record_demo.js   — Playwright headless recorder for the demo GIF
  record_demo.sh   — webm → GIF wrapper around ffmpeg
diagram.md         — system block diagram (mermaid + ASCII)
diagram.png        — rendered mermaid diagram
README.md          — this file
README_ASSIGNMENT.md  — the original assignment brief
.env.example
```
