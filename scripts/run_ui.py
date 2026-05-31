"""
Run the private trading-bot UI.
"""

from __future__ import annotations

import sys
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
load_dotenv()

from config import UI_BIND_HOST, UI_PORT


def main() -> None:
    uvicorn.run("ui.app:app", host=UI_BIND_HOST, port=UI_PORT, reload=False)


if __name__ == "__main__":
    main()
