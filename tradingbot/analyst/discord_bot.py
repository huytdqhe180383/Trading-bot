"""Discord bot bridge for analyst-only interaction."""

from __future__ import annotations

import asyncio
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
from tradingbot.execution.service import create_default_execution_service


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

    def format_order_event(self, event: Any) -> str:
        data = event.to_public_dict() if hasattr(event, "to_public_dict") else dict(event)
        payload = data.get("payload", {}) if isinstance(data.get("payload", {}), dict) else {}
        order = payload.get("order", {}) if isinstance(payload.get("order", {}), dict) else {}
        lines = [str(data.get("title", "Order suggestion")), str(data.get("message", ""))]
        if order:
            lines.extend(
                [
                    f"Instrument: {order.get('inst_id', data.get('symbol', ''))}",
                    f"Side/type: {str(order.get('side', '')).upper()} / {str(order.get('ord_type', '')).upper()}",
                    f"Size: {order.get('size', '')} {order.get('size_unit', '')}",
                    f"Limit price: {order.get('price') or 'market'}",
                    f"Max slippage: {_pct(order.get('slippage_pct', 0))}",
                    f"Estimated notional: {order.get('estimated_notional_usdt', 'n/a')} USDT",
                ]
            )
        if payload.get("expires_at_utc"):
            lines.append(f"Expires: {payload['expires_at_utc']}")
        lines.append("Demo only. Confirming will re-check balance, open orders, positions, liquidity, and slippage.")
        return "\n".join(line for line in lines if line)[:1900]


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

    def send_order_suggestion(self, event: Any) -> bool:
        if not self.enabled():
            return False
        formatter = DiscordAnalystBot(service=None, config=self.config)
        data = event.to_public_dict() if hasattr(event, "to_public_dict") else dict(event)
        suggestion_id = str(data.get("payload", {}).get("suggestion_id", ""))
        if not suggestion_id:
            return False
        payload = {
            "content": formatter.format_order_event(event),
            "components": [_order_button_row(suggestion_id)],
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


def _order_button_row(suggestion_id: str) -> dict[str, Any]:
    return {
        "type": 1,
        "components": [
            {"type": 2, "style": 3, "label": "Confirm & submit demo order", "custom_id": f"order:confirm:{suggestion_id}"},
            {"type": 2, "style": 4, "label": "Reject", "custom_id": f"order:reject:{suggestion_id}"},
        ],
    }


def _pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return "n/a"


def format_account_context(context: dict[str, Any]) -> str:
    lines = ["OKX demo account snapshot", f"As of: {context.get('as_of_utc', 'n/a')}"]
    account = context.get("account", {})
    if account.get("totalEq"):
        lines.append(f"Total equity: {account['totalEq']}")
    balances = context.get("balances", [])
    lines.append("Balances:")
    lines.extend(
        f"- {row.get('ccy', '')}: available {row.get('avail_bal', '0')}, equity {row.get('equity', '0')}"
        for row in balances[:12]
    )
    orders = context.get("open_orders", [])
    lines.append(f"Open spot orders: {len(orders)}")
    for row in orders[:8]:
        lines.append(f"- {row.get('instId', '')} {str(row.get('side', '')).upper()} {row.get('sz', '')} {row.get('state', '')}")
    positions = context.get("positions", [])
    lines.append(f"Open positions: {len(positions)}")
    for row in positions[:8]:
        lines.append(f"- {row.get('instId', '')} {row.get('pos', '')} avg {row.get('avgPx', '')} UPL {row.get('upl', '')}")
    return "\n".join(lines)[:1900]


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
    execution_service = create_default_execution_service(analyst_service=service)
    notifier = DiscordNotifier(config=config)
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

    @tree.command(name="news", description="Show latest OKX announcements.")
    async def news_cmd(interaction: discord.Interaction, symbol: str = "ALL") -> None:
        _check(interaction)
        event = service.latest_news(symbol=symbol)
        await _reply(interaction, bridge.format_event(event))

    @tree.command(name="account", description="Show the private OKX demo account snapshot.")
    async def account_cmd(interaction: discord.Interaction, symbol: str = "ALL") -> None:
        _check(interaction)
        await interaction.response.defer(ephemeral=True)
        context = await asyncio.to_thread(
            execution_service.account_context,
            symbol="" if str(symbol).strip().upper() == "ALL" else symbol,
        )
        await interaction.followup.send(format_account_context(context), ephemeral=True)

    @tree.command(name="suggest", description="Ask the multi-agent planner for a confirmed demo order suggestion.")
    async def suggest_cmd(interaction: discord.Interaction, instruction: str, symbol: str = "BTCUSDT") -> None:
        _check(interaction)
        await interaction.response.defer(ephemeral=True)
        event = await asyncio.to_thread(
            execution_service.suggest_order,
            symbol=symbol,
            instruction=instruction,
            requested_by=str(interaction.user.id),
        )
        sent = False
        dispatch_error = ""
        if event.status == "pending":
            try:
                sent = await asyncio.to_thread(notifier.send_order_suggestion, event)
            except Exception as exc:
                dispatch_error = f"Suggestion created but Discord dispatch failed: {exc}"[:1900]
        if dispatch_error:
            await interaction.followup.send(dispatch_error, ephemeral=True)
        elif sent:
            await interaction.followup.send(
                f"Suggestion `{event.payload.get('suggestion_id', '')}` sent to the confirmation channel.",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(bridge.format_order_event(event), ephemeral=True)

    @client.event
    async def on_interaction(interaction: discord.Interaction) -> None:
        if interaction.type != discord.InteractionType.component:
            return
        data = getattr(interaction, "data", {}) or {}
        custom_id = str(data.get("custom_id", "")) if isinstance(data, dict) else ""
        if not custom_id.startswith(("analyst:", "order:")):
            return
        _check(interaction)
        parts = custom_id.split(":", 2)
        action = parts[1] if len(parts) > 1 else ""
        alert_id = parts[2] if len(parts) > 2 else ""
        if custom_id.startswith("order:"):
            await interaction.response.defer(ephemeral=True)
            if action == "confirm":
                event = await asyncio.to_thread(
                    execution_service.confirm_order,
                    suggestion_id=alert_id,
                    requested_by=str(interaction.user.id),
                )
            elif action == "reject":
                event = await asyncio.to_thread(
                    execution_service.reject_order,
                    suggestion_id=alert_id,
                    requested_by=str(interaction.user.id),
                )
            else:
                await interaction.followup.send("Unsupported order action.", ephemeral=True)
                return
            await interaction.followup.send(bridge.format_order_event(event), ephemeral=True)
            return
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
            event = service.latest_news(alert_id=alert_id)
            await _reply(interaction, bridge.format_event(event))
            return
        await _reply(interaction, "Unsupported analyst action.")

    @client.event
    async def on_ready() -> None:
        if config.guild_id:
            await tree.sync(guild=discord.Object(id=int(config.guild_id)))
        else:
            await tree.sync()

    client.run(config.bot_token)
