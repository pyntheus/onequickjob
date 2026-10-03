"""Where seed JSON lives: <repo>/seed (mounted at /app/seed in the api container)."""

import os
from pathlib import Path

SEED_DIR = Path(os.environ.get("SEED_DIR") or Path(__file__).resolve().parents[3] / "seed")
