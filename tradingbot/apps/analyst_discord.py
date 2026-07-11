"""Application entrypoint for the analyst Discord bot."""


def main() -> None:
    from tradingbot.analyst.discord_bot import run_discord_bot

    run_discord_bot()
