"""Copia lambda_function.py in build/ per il pacchetto ZIP (nessuna dipendenza pip)."""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
HANDLER = ROOT / "lambda_function.py"


def main() -> None:
    if BUILD.exists():
        shutil.rmtree(BUILD)
    BUILD.mkdir(parents=True)
    shutil.copy(HANDLER, BUILD / "lambda_function.py")
    print(f"OK: {BUILD}")


if __name__ == "__main__":
    main()
