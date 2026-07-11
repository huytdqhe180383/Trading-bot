"""Application entrypoint for the analyst scanner."""


def main() -> None:
    import argparse

    from tradingbot.analyst.scanner import create_default_scanner

    parser = argparse.ArgumentParser(description="Run analyst-only public-data scanner.")
    parser.add_argument("--max-cycles", type=int, default=0)
    args = parser.parse_args()
    create_default_scanner().run_forever(max_cycles=args.max_cycles)
