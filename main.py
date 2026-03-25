"""Root ASGI entrypoint shim.

Allows running from repository root with:
    uv run uvicorn main:app --reload
"""

from pathlib import Path
import sys

# Make backend package path importable when running from repo root.
BACKEND_DIR = Path(__file__).resolve().parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from backend.main import app  # noqa: E402
