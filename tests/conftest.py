"""Hace importable el paquete src/ sin instalar nada."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
