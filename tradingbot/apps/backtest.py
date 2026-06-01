"""Application entrypoint for backtesting."""


def main() -> None:
    from backtest import main as backtest_main

    backtest_main()
