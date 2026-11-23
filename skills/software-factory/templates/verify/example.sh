#!/usr/bin/env bash
# A recipe exercises ONE feature end to end and exits non-zero when it is broken.
# Rules: self-contained (own server, free port, temp data), fast (seconds), deterministic,
# non-interactive. Print what you saw: the output becomes the evidence in the report.
set -euo pipefail
echo "replace this with a real check of the feature" >&2
exit 1
