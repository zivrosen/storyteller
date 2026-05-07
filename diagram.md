# System Block Diagram

## Mermaid

```mermaid
flowchart TD
    User([User Request<br/>CLI prompt])

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
    Tweak["6 - User Feedback<br/>(interactive CLI)<br/><br/>Enter = accept<br/>text = User Tweak prompt"]
    UserTweak["User Tweak<br/>(LLM, targeted edits<br/>from free-form request)"]

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

## ASCII

```
                       ┌────────────────────────┐
                       │   User Request          │
                       │   (CLI prompt)          │
                       └────────────┬────────────┘
                                    │ free-form text
                                    ▼
                       ┌────────────────────────┐
                       │   1. Categorizer        │
                       │   (LLM, JSON mode)      │
                       │                         │
                       │   → category            │
                       │   → named characters    │
                       │   → themes              │
                       │   → tone_hint           │
                       │   → target_length       │
                       └────────────┬────────────┘
                                    │ StoryRequest
                                    ▼
                       ┌────────────────────────┐
                       │   2. Story Planner      │
                       │   (LLM, JSON mode)      │
                       │                         │
                       │   4-beat outline:       │
                       │     • SETUP             │
                       │     • SPARK             │
                       │     • RESOLUTION        │
                       │     • WIND_DOWN  ◄──── enforced as the bedtime-specific beat
                       └────────────┬────────────┘
                                    │ StoryPlan
                                    ▼
                       ┌────────────────────────┐
                       │   3. Storyteller        │
                       │   (LLM, prose)          │
                       │                         │
                       │   target words, tone,   │
                       │   banned-content list,  │
                       │   wind-down required    │
                       └────────────┬────────────┘
                                    │ Draft
                                    ▼
                       ┌────────────────────────┐
                       │   4. Judge              │ ◄────────────┐
                       │   (LLM, JSON mode)      │              │
                       │                         │              │
                       │   7-dim rubric:         │              │
                       │   age_appropriateness   │              │
                       │   bedtime_suitability   │              │
                       │   narrative_coherence   │              │
                       │   vocabulary_level      │              │
                       │   safety                │              │
                       │   ending_calmness       │              │
                       │   character_consistency │              │
                       │                         │              │
                       │   pass = all >= 4/5     │              │
                       └────┬───────────────┬────┘              │
                            │ pass          │ fail              │
                            ▼               ▼                   │
                       ┌─────────┐     ┌─────────────────┐      │
                       │ Display │     │  5. Refiner     │ ─────┘
                       │  Story  │     │  (LLM, targeted │   max 2 iterations
                       │  + read │     │   edits, NOT a  │
                       │   time  │     │   full rewrite) │
                       └────┬────┘     └─────────────────┘
                            │
                            ▼
                       ┌────────────────────────┐
                       │   6. User Feedback      │
                       │   (interactive CLI)     │
                       │                         │
                       │   Enter   → accept      │
                       │   text    → User Tweak  │
                       │             prompt re-  │
                       │             applies     │
                       │             targeted    │
                       │             edits       │
                       └────────────────────────┘
```

## Key design choices

- **WIND_DOWN as a first-class beat AND a judge dimension.** A generic
  children's-story prompt will end with cheering or action. Bedtime stories
  must end with the world quieting and a closing line that points toward
  sleep. We enforce this both upstream (in the planner) and downstream (in
  the judge), so the refinement loop has a specific target if it drifts.

- **Multi-stage decomposition.** We are constrained to gpt-3.5-turbo per the
  assignment. Single-shot prompting on this model produces uneven structure.
  Splitting into categorize → plan → tell → judge gives each call a smaller,
  well-scoped job and yields more reliable structure than one big prompt.

- **Refinement is targeted, not regenerative.** The refiner prompt receives
  the prior draft + the per-dimension critique block sorted lowest-score
  first, and is instructed to make edits rather than rewrite. This preserves
  what the judge already approved.

- **Judge JSON parser is strict.** Even if the model claims `overall_pass:
  true`, the parser overrides to `false` if any dimension scored below the
  threshold. Missing or malformed dimensions default to score 3 (failing) so
  the refinement loop is forced rather than silently passing through.

- **User feedback uses a different prompt than auto-refinement.** The auto
  refiner addresses an editor's structured rubric; the user-tweak prompt
  treats free-form natural-language requests as the source of truth. Mixing
  them in one template produced muddled edits.

- **Iteration cap of 2.** Empirically clears the threshold the vast majority
  of the time. Beyond 2, marginal quality gains are small relative to
  latency and API cost.
```
