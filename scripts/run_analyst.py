"""Compatibility wrapper for the analyst-only scanner."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradingbot.apps.analyst import main


if __name__ == "__main__":
    main()
