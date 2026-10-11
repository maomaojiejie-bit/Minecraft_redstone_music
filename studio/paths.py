from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
SKILL_DIR = BASE_DIR / "minecraft-redstone-music"
SCRIPTS_DIR = SKILL_DIR / "scripts"
ASSETS_DIR = SKILL_DIR / "assets"
BINARIES_DIR = BASE_DIR / "binaries"
OUTPUT_DIR = BASE_DIR / "output"
PYTHON = sys.executable or "python"


def script_path(name: str) -> str:
    return str(SCRIPTS_DIR / name)


def ensure_dir(path):
    Path(path).mkdir(parents=True, exist_ok=True)
    return str(path)
