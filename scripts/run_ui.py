"""
Run the private trading-bot UI.
"""

from __future__ import annotations

import uvicorn

from config import UI_BIND_HOST, UI_PORT


def main() -> None:
    uvicorn.run("ui.app:app", host=UI_BIND_HOST, port=UI_PORT, reload=False)


if __name__ == "__main__":
    main()
