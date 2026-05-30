"""
Minimal .env loader for the rig — zero dependencies.

Importing this module reads `KEY=value` pairs from a `.env` file (located next
to this file) into os.environ, WITHOUT overriding anything already set in the
real environment — so an explicit `export FOO=bar` in your shell always wins.

Usage: just `import rig_env` once, early, in any entry point (proxy.py,
ab_runner.py). It runs load_env() on import.

The `.env` file is shell-sourceable too: its lines use `export KEY=value`, so
the SAME file configures both the rig's Python AND the shell that launches
mini-swe-agent (`source .env`).

Copy `.env.example` -> `.env`, then put your real key in `.env`. `.env` is
gitignored; `.env.example` is the safe-to-commit template (no secrets).
"""

import os

# This file lives at <repo>/src/rig/rig_env.py; the .env sits at the repo root,
# three levels up. (.env stays shell-sourceable from the repo root too.)
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DEFAULT_ENV = os.path.join(_REPO_ROOT, ".env")


def load_env(path: str = _DEFAULT_ENV) -> int:
    """Load KEY=value lines from `path` into os.environ (existing env wins).

    Returns how many variables were set (0 if the file is absent).
    """
    if not os.path.exists(path):
        return 0
    n = 0
    with open(path) as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            if key.startswith("export "):            # allow shell-style `export FOO=bar`
                key = key[len("export "):].strip()
            val = val.strip().strip('"').strip("'")   # drop surrounding quotes
            if key and key not in os.environ:         # real env always wins
                os.environ[key] = val
                n += 1
    return n


# Load on import, so a bare `import rig_env` is enough.
load_env()
