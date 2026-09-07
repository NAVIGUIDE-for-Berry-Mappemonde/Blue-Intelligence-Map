#!/usr/bin/env python3
"""Point d'entrée CDC : délègue à backend/scripts/export_master_seeds.py."""
from pathlib import Path
import runpy

runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "backend" / "scripts" / "export_master_seeds.py"),
    run_name="__main__",
)
