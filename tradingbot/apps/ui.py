"""Application entrypoint for the private bot UI."""


def main() -> None:
    from scripts.run_ui import main as ui_main

    ui_main()
