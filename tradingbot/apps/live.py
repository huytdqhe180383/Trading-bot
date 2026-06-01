"""Application entrypoint for live/testnet execution."""


def main() -> None:
    from scripts.run_live import main as live_main

    live_main()
