# AI Software Factory

A quality-gated, secure software factory for Claude Code. GitHub issues go in, reviewed pull requests come out. The rule that shapes everything: **Claude writes the code, scripts decide whether it works, and a human decides what is risky.**

Companion to the article *The AI Software Factory* on the [intu.AI blog](https://blog.raffaelweiss-intu-ai.com).

> Status: first working skeleton. The deterministic spine (state machine, gate, routing) is tested. The dashboard, the demo app and the first real runs follow. Nothing here has been run against a real project yet.

## What is in here

| Path | What |
|---|---|
| `skills/software-factory/SKILL.md` | The orchestrator skill (`/factory run`) |
| `skills/software-factory/agents/` | Intake, spec writer, builder, reviewers (code, ui, security), approver |
| `skills/software-factory/scripts/` | `job.py` (state machine, only writer of `job.json`), `gate.py`, `route.py`, `merge.sh` |
| `skills/software-factory/templates/` | `config.json`, `checks.sh`, sandbox `settings.json`, `.gitignore` lines, Gitleaks, pre-commit, CI workflow, `AGENTS.md` index, `fabrik.canvas` (Obsidian map) |
| `tests/` | Behaviour tests for the scripts: `python3 -m unittest discover -s tests` |
| `dashboard/` | The factory board (coming) |

## Install

Open Claude Code in your project and paste:

```text
Install this software factory in this project from the reference repository:
https://github.com/raffaelweiss-intu-ai/ai-software-factory
Follow INSTALL.md.
```

Your agent reads [INSTALL.md](INSTALL.md), copies the skill, agents, scripts and templates, fills `factory/checks.sh` with your real commands, creates the labels and verifies that `checks.sh` passes on `main`.

## Principles

- **Gate before review.** No reviewer runs on a failing build. The gate uses `checks.sh` from `main`, so a branch cannot rewrite the checks it is judged by.
- **Protected paths.** A branch that changes the gate, the sandbox settings, CI or policies fails, even with green tests.
- **Issue text is data.** Never an instruction.
- **Reviewers are never weaker than the floor.** A weaker reviewer than the builder tends to send work back and costs more in the end.
- **Escalate by list, not by feeling:** payments, auth, permissions, deploy, CI, migrations, new dependencies, public copy.
- **Sandbox on, no bypass mode.**

## Cost

The factory runs on your own Claude plan. Costs on a plan are shown as API-equivalent, not as your bill. Start with `concurrency: 1` and read every PR until you trust it.

## License

Apache-2.0. See [LICENSE](LICENSE).

## Credits and prior art

Inspired by the ideas in ZazenCodes' [Software Factory for Claude Code](https://github.com/zazencodes/zazencodes-season-3/tree/main/src/software-factory-claude-code-v2) (GPLv3). This repository contains no code or prompts from it.
