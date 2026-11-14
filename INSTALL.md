# Install (instructions for the installing agent)

You are installing the software factory from this repository into the user's project. Work in the project root. Ask before anything that costs money.

1. **Preconditions.** `git`, `python3` (3.10+), `gh` authenticated with push access, Claude Code with sandboxing available. The project must be a GitHub repository with a working test command. If any is missing, say so and stop.
2. **Copy.**
   - `skills/software-factory/SKILL.md` -> `.claude/skills/factory/SKILL.md`
   - `skills/software-factory/agents/*.md` -> `.claude/agents/`
   - `skills/software-factory/scripts/*` -> `factory/bin/`
   - `skills/software-factory/templates/config.json`, `checks.sh` -> `factory/`
   - `skills/software-factory/templates/settings.json` -> `.claude/settings.json` (merge with an existing file; never drop existing `deny` rules). Replace `<ABSOLUTE-PROJECT-PATH>` with the project's absolute path: builders commit from git worktrees, and the sandbox only allows that when the project's `.git` is listed. `hooks` and `config` inside `.git` stay protected
   - `templates/workflows/gates.yml` -> `.github/workflows/gates.yml`; `gitleaks.toml` -> `.gitleaks.toml`; `pre-commit-config.yaml` -> `.pre-commit-config.yaml`
   - Append `templates/gitignore.snippet` to `.gitignore` (skip lines already present).
3. **Fill `factory/checks.sh`** with this project's real lint, typecheck, test and build commands. Run it on `main`. It must pass before you continue.
4. **Tailor** the reviewers to the stack: edit the stack-specific lines in `reviewer-code.md` and `reviewer-ui.md`; if the project has no UI, delete `reviewer-ui.md` and the `ui` entry in `factory/config.json`.
5. **Add the index.** Merge `templates/AGENTS-section.md` into the project's `AGENTS.md`, adapting the paths to what exists. Do not invent files.
6. **Create the labels:** `factory`, `factory:needs-info`, `factory:needs-human`.
7. **Obsidian (optional).** Copy `templates/fabrik.canvas` into the user's vault.
8. **Verify.** Run `python3 -m unittest discover -s tests` in this repository's checkout if available, then create one low-risk test issue labeled `factory` and run `/factory run 1` with `concurrency: 1`. Report what ran and what did not.
9. **Report** what was installed, what you adapted and what is still untested. Do not claim the factory works until a job went through end to end.
