"""Crea la cartella build/ con dipendenze pip + lambda_function.py per il pacchetto ZIP."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
REQ = ROOT / "requirements.txt"
HANDLER = ROOT / "lambda_function.py"


def main() -> None:
    if BUILD.exists():
        shutil.rmtree(BUILD)
    BUILD.mkdir(parents=True)
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "-r", str(REQ), "-t", str(BUILD)],
    )
    shutil.copy(HANDLER, BUILD / "lambda_function.py")
    print(f"OK: {BUILD}")


if __name__ == "__main__":
    main()
