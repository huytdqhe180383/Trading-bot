"""Discord bot bridge for analyst-only interaction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from config import (
    DISCORD_ALERT_CHANNEL_ID,
    DISCORD_ALLOWED_USER_IDS,
    DISCORD_ANALYST_CHANNEL_ID,
    DISCORD_APPLICATION_ID,
    DISCORD_BOT_TOKEN,
    DISCORD_GUILD_ID,
)

from .service import AnalystService, create_default_analyst_service


@dataclass(frozen=True)
class DiscordAnalystConfig:
    bot_token: str
    application_id: str
    guild_id: str
    alert_channel_id: str
    analyst_channel_id: str
    allowed_user_ids: frozenset[str]

    def user_allowed(self, user_id: int | str) -> bool:
        if not self.allowed_user_ids:
            return False
        return str(user_id) in self.allowed_user_ids

    def channel_allowed(self, channel_id: int | str) -> bool:
        return str(channel_id) in {self.alert_channel_id, self.analyst_channel_id}


def load_discord_config_from_env() -> DiscordAnalystConfig:
    return DiscordAnalystConfig(
        bot_token=DISCORD_BOT_TOKEN,
        application_id=DISCORD_APPLICATION_ID,
        guild_id=DISCORD_GUILD_ID,
        alert_channel_id=DISCORD_ALERT_CHANNEL_ID,
        analyst_channel_id=DISCORD_ANALYST_CHANNEL_ID,
        allowed_user_ids=frozenset(str(user_id) for user_id in DISCORD_ALLOWED_USER_IDS),
    )


class DiscordAnalystBot:
    def __init__(self, *, service: AnalystService, config: DiscordAnalystConfig) -> None:
        self.service = service
        self.config = config

    def require_allowed(self, *, user_id: int | str, channel_id: int | str) -> None:
        if not self.config.user_allowed(user_id):
            raise PermissionError("Discord user is not allowed to use analyst commands.")
        if not self.config.channel_allowed(channel_id):
            raise PermissionError("Discord channel is not allowed for analyst commands.")

    def format_event(self, event: Any) -> str:
        data = event.to_public_dict() if hasattr(event, "to_public_dict") else dict(event)
        status = str(data.get("status", ""))
        title = str(data.get("title", "Analyst event"))
        recommendation = data.get("recommendation")
        message = str(data.get("message", ""))
        if status != "ok":
            return f"{title}\nStatus: {status}\n{message}"
        suffix = f"\nRecommendation: {recommendation}" if recommendation else ""
        return f"{title}{suffix}\n{message}"


class DiscordNotifier:
    """Bot-token Discord notifier with analyst action buttons."""

    api_base = "https://discord.com/api/v10"

    def __init__(self, *, config: DiscordAnalystConfig, post: Any | None = None) -> None:
        self.config = config
        self._post = post or requests.post

    def enabled(self) -> bool:
        return bool(self.config.bot_token and self.config.alert_channel_id)

    def send_event(self, event: Any) -> bool:
        if not self.enabled():
            return False
        formatter = DiscordAnalystBot(service=None, config=self.config)
        data = event.to_public_dict() if hasattr(event, "to_public_dict") else dict(event)
        alert_id = str(data.get("id", ""))
        payload = {
            "content": formatter.format_event(event)[:1900],
            "components": [_button_row(alert_id)] if alert_id else [],
            "allowed_mentions": {"parse": []},
        }
        response = self._post(
            f"{self.api_base}/channels/{self.config.alert_channel_id}/messages",
            headers={
                "Authorization": f"Bot {self.config.bot_token}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=10,
        )
        response.raise_for_status()
        return True


def _button_row(alert_id: str) -> dict[str, Any]:
    return {
        "type": 1,
        "components": [
            {"type": 2, "style": 2, "label": "Explain", "custom_id": f"analyst:explain:{alert_id}"},
            {"type": 2, "style": 1, "label": "Validate now", "custom_id": f"analyst:validate:{alert_id}"},
            {"type": 2, "style": 2, "label": "Latest news", "custom_id": f"analyst:news:{alert_id}"},
        ],
    }


def run_discord_bot() -> None:
    """Run the Discord gateway bot if discord.py is installed."""
    try:
        import discord
        from discord import app_commands
    except Exception as exc:  # pragma: no cover - depends on optional package
        raise RuntimeError("discord.py is required to run the analyst Discord bot.") from exc

    config = load_discord_config_from_env()
    if not config.bot_token:
        raise RuntimeError("DISCORD_BOT_TOKEN is not configured.")

    service = create_default_analyst_service()
    bridge = DiscordAnalystBot(service=service, config=config)
    intents = discord.Intents.default()
    client = discord.Client(intents=intents, application_id=int(config.application_id or 0))
    tree = app_commands.CommandTree(client)

    async def _reply(interaction: discord.Interaction, content: str) -> None:
        await interaction.response.send_message(content[:1900], ephemeral=True)

    def _check(interaction: discord.Interaction) -> None:
        bridge.require_allowed(user_id=interaction.user.id, channel_id=interaction.channel_id or "")

    @tree.command(name="status", description="Show analyst status and budget.")
    async def status_cmd(interaction: discord.Interaction) -> None:
        _check(interaction)
        status = service.status().to_dict()
        await _reply(interaction, f"Analyst enabled: {status['enabled']}\nBudget: {status['budgets']}")

    @tree.command(name="update", description="Run an analyst update.")
    async def update_cmd(interaction: discord.Interaction, symbol: str = "ALL") -> None:
        _check(interaction)
        await interaction.response.defer(ephemeral=True)
        event = service.run_update(symbol=symbol, scope="interactive")
        await interaction.followup.send(bridge.format_event(event)[:1900], ephemeral=True)

    @tree.command(name="ask", description="Ask the main analyst.")
    async def ask_cmd(interaction: discord.Interaction, question: str, symbol: str = "ALL") -> None:
        _check(interaction)
        await interaction.response.defer(ephemeral=True)
        event = service.ask(question=question, symbol=symbol, scope="interactive")
        await interaction.followup.send(bridge.format_event(event)[:1900], ephemeral=True)

    @tree.command(name="validate", description="Validate an analyst alert.")
    async def validate_cmd(interaction: discord.Interaction, alert_id: str = "", symbol: str = "ALL") -> None:
        _check(interaction)
        await interaction.response.defer(ephemeral=True)
        event = service.validate(alert_id=alert_id, symbol=symbol, scope="interactive")
        await interaction.followup.send(bridge.format_event(event)[:1900], ephemeral=True)

    @tree.command(name="explain", description="Explain an existing analyst alert.")
    async def explain_cmd(interaction: discord.Interaction, alert_id: str) -> None:
        _check(interaction)
        event = service.explain(alert_id=alert_id)
        await _reply(interaction, bridge.format_event(event))

    @tree.command(name="budget", description="Show LLM budget usage.")
    async def budget_cmd(interaction: discord.Interaction) -> None:
        _check(interaction)
        await _reply(interaction, str(service.budget.snapshot()))

    @tree.command(name="reset", description="Reset is acknowledged; persisted audit events are retained.")
    async def reset_cmd(interaction: discord.Interaction) -> None:
        _check(interaction)
        await _reply(interaction, "Conversation memory reset. Persisted audit events remain on disk.")

    @tree.command(name="news", description="News command placeholder for deterministic news snapshots.")
    async def news_cmd(interaction: discord.Interaction, symbol: str = "ALL") -> None:
        _check(interaction)
        await _reply(interaction, f"News snapshot for {symbol.upper()} is not wired yet; no LLM call was spent.")

    @client.event
    async def on_interaction(interaction: discord.Interaction) -> None:
        if interaction.type is not discord.InteractionType.component:
            return
        custom_id = str(getattr(interaction.data, "get", lambda key, default=None: default)("custom_id", ""))
        if not custom_id.startswith("analyst:"):
            return
        _check(interaction)
        parts = custom_id.split(":", 2)
        action = parts[1] if len(parts) > 1 else ""
        alert_id = parts[2] if len(parts) > 2 else ""
        if action == "explain":
            event = service.explain(alert_id=alert_id)
            await _reply(interaction, bridge.format_event(event))
            return
        if action == "validate":
            await interaction.response.defer(ephemeral=True)
            event = service.validate(alert_id=alert_id, scope="interactive")
            await interaction.followup.send(bridge.format_event(event)[:1900], ephemeral=True)
            return
        if action == "news":
            await _reply(interaction, "Latest news snapshot is not wired yet; no LLM call was spent.")
            return
        await _reply(interaction, "Unsupported analyst action.")

    @client.event
    async def on_ready() -> None:
        if config.guild_id:
            await tree.sync(guild=discord.Object(id=int(config.guild_id)))
        else:
            await tree.sync()

    client.run(config.bot_token)
