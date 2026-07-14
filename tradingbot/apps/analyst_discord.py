"""Application entrypoint for the analyst Discord bot."""


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv()

    from tradingbot.analyst.discord_bot import run_discord_bot

    run_discord_bot()
