"""Ancien utilitaire Albania — POST generate a été retiré (410)."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.routers.formalities import GENERATE_GONE  # noqa: E402

print("POST /api/poe/zones/{mrgid}/generate is gone (410).")
print(GENERATE_GONE)
raise SystemExit(1)
