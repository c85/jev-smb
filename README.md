# Mario + Jev

This repository is a local working version of the Mario + Jev project. The
starting codebase came from [shantanugoel/mario-jev](https://github.com/shantanugoel/mario-jev).
This repository contains the local dashboard, route runner, replay updates,
level-specific policy experiments, and evaluation changes described below.

The project uses Jev through the TypeSafe SDK to control NES Super Mario Bros.
Jev receives structured RAM-derived observations and returns typed judgments for
movement, jump timing, ceiling hops, and sustaining a jump. The controller
composes those judgments into emulator button actions and records each decision
to a JSONL log.

## Setup

Requirements:

- Python 3.13 or newer
- [uv](https://docs.astral.sh/uv/)
- A TypeSafe API key for the Jev policy

Install dependencies and create the local environment:

```bash
uv sync --locked
cp .env.example .env
```

Set the key in `.env`:

```dotenv
TYPESAFE_API_KEY=your-key-here
```

Do not commit `.env`, API keys, gameplay logs, or ROM files.

## Running the emulator

Run a visible Jev-controlled World 1-1 attempt:

```bash
uv run mario-jev --world 1 --stage 1 --decisions 500
```

Run World 1-2 directly:

```bash
uv run mario-jev --world 1 --stage 2 --decisions 500
```

Run World 1-1 and automatically continue into World 1-2 after the flag is
reached:

```bash
uv run mario-jev --policy jev --route 1-1,1-2 --decisions 500
```

The route runner keeps the same Jev client, resets level-local observation
history at the handoff, and activates the World 1-2 profile when the second
level starts. If a level ends without completion, the route stops.

Useful options:

```bash
# Run without opening an emulator window
uv run mario-jev --world 1 --stage 2 --headless

# Run the scripted baseline without an API key
uv run mario-jev --policy scripted --headless --episodes 3

# Inspect the initial decoded state without model calls
uv run mario-jev --dump-state --headless

# Change the maximum frames held per controller decision
uv run mario-jev --frames 4 --decisions 200
```

Each decision normally holds an action for four emulator frames by default.
The runner checks RAM after every frame and interrupts an action early when
Mario lands, dies, or completes the level.

## Live dashboard

Start a visible run with the local dashboard:

```bash
uv run mario-jev --world 1 --stage 2 --dashboard
```

The dashboard opens at `http://127.0.0.1:8765/`. It includes:

- A live emulator frame
- Current level, progress, reward, position, and time
- Current action and Jev decision details
- Recent events and transition history
- Position and decision charts
- A responsive two-column layout for desktop browsers

For a headless emulator with a live dashboard stream:

```bash
uv run mario-jev --world 1 --stage 2 --headless --dashboard
```

Headless dashboard runs still honor real-time playback speed. The emulator
window is omitted, but the dashboard receives live PNG frames.

## Replay

Every live run writes a timestamped JSONL file under `runs/`. Replay a log
without making new API calls:

```bash
uv run mario-jev --replay runs/your-run.jsonl
```

Replay with the dashboard or in headless mode:

```bash
uv run mario-jev --replay runs/your-run.jsonl --dashboard --speed 1
uv run mario-jev --replay runs/your-run.jsonl --headless --dashboard --speed 1
```

Replay validates recorded positions and actual frame counts. Route logs record
the active environment and stage index so a 1-1 → 1-2 run can be replayed with
the same level transition.

## Changes in this repository

Compared with the upstream starting point, this working version adds or extends:

- A modern local dashboard titled **Jev Plays Super Mario Bros.**
- Smooth live frame streaming through a binary PNG endpoint and browser polling
- A desktop two-column dashboard layout that avoids unnecessary vertical scrolling
- The `--route` option for continuous multi-level runs such as `1-1,1-2`
- Route-aware JSONL logging and deterministic replay
- Environment-aware Jev policy switching at level boundaries
- World 1-2 opening logic for the low-ceiling two-Goomba sequence
- A World 1-2 green-Koopa approach guard that prevents braking into a nearby threat
- Richer transition diagnostics for blocked movement, head bumps, gaps, ceilings,
  landing surfaces, recent frames, and jump state
- Tests for the dashboard, route parsing, route-aware policy behavior, replay,
  state extraction, history, and frame execution

The World 1-2 rules are intentionally scoped to that level so experiments there
do not change World 1-1 behavior. The controller does not train online; history
is bounded, episode-local context for Jev decisions and logging.

## Current limitations

- Jev calls require network access and can fail because of transient API errors.
- Jev responses are not guaranteed to be identical across separate trials, even
  with the same emulator seed; compare multiple evaluations when measuring progress.
- The current World 1-2 profile handles selected observed hazards, but is not a
  complete route script.
- Forward-stall detection is recorded, but automatic recovery from a Mario who
  is pressing into a brick wall is not yet implemented.
- Gameplay logs contain decisions and observations, not video or saved emulator
  snapshots.

## Development

Run the test suite and lint checks:

```bash
uv run pytest -q
uv run ruff check src tests
```

The main modules are:

- `src/mario_jev/cli.py` — command-line runner, routes, logging, and dashboard wiring
- `src/mario_jev/policy.py` — Jev judgments, action composition, and level profiles
- `src/mario_jev/state.py` — SMB1 RAM decoding and terrain context
- `src/mario_jev/history.py` — bounded episode-local transition and jump memory
- `src/mario_jev/runner.py` — per-frame action execution and landing interruption
- `src/mario_jev/dashboard.py` — local live dashboard and frame server
- `src/mario_jev/replay.py` — API-free deterministic playback and verification

The project does not distribute ROM files. The emulator and game assets come
from the installed emulator dependencies.
