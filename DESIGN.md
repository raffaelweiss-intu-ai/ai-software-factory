# Design

The factory is a small deterministic spine with agents for judgment in between.

| Piece | File | Job |
|---|---|---|
| Queue | GitHub issues with label `factory` | What to build. The label is the trust boundary. |
| Orchestrator | `SKILL.md` | Starts jobs, spawns agents, calls scripts. Writes nothing itself. |
| Agents | `agents/*.md` | One file each: read files, write exactly one file, reply with one line. |
| State | `factory/jobs/<id>/` | `job.json` plus every agent's file. Local, gitignored. |
| Spine | `job.py`, `gate.py`, `route.py`, `merge.sh` | Deterministic. `job.py` is the only writer of `job.json` and refuses illegal moves. |
| Checks | `factory/checks.sh` | The project's real checks. |
| Exit | the pull request | Merging happens only through `merge.sh`, after APPROVE. |

## Stages

`intake -> spec -> build -> gate -> review -> approve -> merging -> merged`, with `needs-info`, `needs-human` and `rejected` as side exits. A failing gate or a review with CHANGES returns to `build` with the next round. After `max_rounds` the job goes to a human. A human's answer adds one extra round.

## Decisions

- **Why scripts decide, not agents.** A rule written only as a sentence is not retrieved when it matters. A script cannot be talked out of it.
- **Why the gate uses `checks.sh` from `main`.** Otherwise a branch could edit the checks it is judged by.
- **Why protected paths fail the gate.** An agent that wants green may change the gate. A change to the gate is a decision for a human.
- **Why a reviewer floor.** A reviewer weaker than the builder tends to misjudge and bounce work back; the rework costs more than the stronger model.
- **Why escalate by list.** "Escalate when unsure" produces second reviews of fine changes. A list of categories gives a human real decisions.
- **Why no bypass mode.** The sandbox and the deny rules are the safety net. Without them, every other rule is a polite request.
- **Why branch mode by default.** The sandbox makes `.git/worktrees/<id>` read-only for a session started elsewhere, so a builder cannot commit from a worktree. One job at a time on a branch in the main checkout works inside the sandbox; parallel jobs need one session per worktree.
- **Why state is files.** A crashed session resumes from the files. In-flight agent work is lost; that is accepted.

## Prior art

ZazenCodes' software factory (GPLv3) inspired the issue queue, the intake step, the gate-before-review order and the job dashboard idea. This design differs in the reviewer floor, the protected-path rule, the sandbox requirement, the escalation list and the Apache-2.0 license, and shares no code.
