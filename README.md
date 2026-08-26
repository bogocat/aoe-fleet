# aoe-fleet

`bogocat.fleet` — an Agent of Empires plugin: pinned launch targets over the
aoe substrate.

The fleet owns the launch surface above aoe. A **target** is the record we keep
re-typing by hand every session start:

```
target = (name, host, dir, harness, model, opening-skill)
```

aoe's own project registry stores path + name only, and `recent-projects.json`
remembers the last tool per path as an MRU, not a pin. Neither carries a host,
a model, or an opening turn — so every session start is a fresh set of decisions
we've already made. The fleet registry pins those decisions; `fleet launch`
turns one entry into a running session.

## Install

```bash
aoe plugin install <path-to-this-repo>
```

The host builds the worker venv into `.aoe-build/` (git-ignored) and grants the
declared capabilities at install.

## Commands

```bash
fleet targets          # list the registry: name, host, dir, harness, model
fleet launch <name>    # turn one target into a running aoe session
```

## Target registry

Shipped defaults live at `src/aoe_fleet/data/default_targets.json`. A user
override at `~/.config/aoe-fleet/targets.json` shadows them (user wins on key
collision); a missing or malformed file falls back to the shipped defaults.

```json
{
  "home-portal": {
    "host": "local",
    "dir": "/root/projects/home-portal",
    "harness": "pi",
    "model": "",
    "opening-skill": ""
  }
}
```

- `host` — optional, defaults to `local`. A non-local value is stored but
  rejected at launch (blocked on upstream agent-of-empires#3545/#3546).
- `harness` — an aoe tool name: a built-in (`pi`, `claude`, `opencode`, `codex`)
  or a custom agent defined in your aoe config under `[session.custom_agents]`.
- `model` — forwarded to `aoe add --model` (meaningful for the structured view);
  for a terminal session, pin a model by pointing `harness` at a custom agent
  whose command carries it (`[session.custom_agents]` + `[session.agent_detect_as]`).
- `opening-skill` — stored now; first-turn injection ships in a later child.

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -e .[dev]
.venv/bin/pytest           # test suite
.venv/bin/ruff check src tests
.venv/bin/mypy src
```

The worker is JSON-RPC 2.0 over ndjson on stdio, dispatched by trailing command
segment (`plugin.bogocat.fleet.targets` → `targets`).
