"""
FastAPI app for the private trading-bot UI.
"""

from __future__ import annotations

import asyncio
import secrets
import subprocess
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from config import (
    LIVE_SESSION_TIMEZONE,
    LOGS_DIR,
    REPORTS_DIR,
    RESULTS_DIR,
    UI_AUDIT_LOG_PATH,
    UI_CONTROL_RATE_LIMIT,
    UI_CONTROL_USE_SUDO,
    UI_CORS_ALLOWED_ORIGINS,
    UI_ENABLE_CONTROLS,
    UI_SESSION_MAX_AGE_SECS,
    UI_SESSION_SECRET,
    UI_TAIL_LINES_DEFAULT,
    UI_TARGET_SERVICE,
)
from ui.services import (
    InMemoryRateLimiter,
    STRATEGY_NAV_NOTE,
    append_ui_audit_log,
    build_control_command,
    build_dashboard_payload,
    build_history_payload,
    build_report_payload,
    mint_csrf_token,
    read_log_source,
    run_control_command,
    safe_compact_report_path,
)
from tradingbot.analyst import AnalystService, create_default_analyst_service
from tradingbot.analyst.market import fetch_public_candles
from tradingbot.analyst.scanner import create_default_scanner
from tradingbot.execution.service import TradingExecutionService, create_default_execution_service

UI_ROOT = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(UI_ROOT / "templates"))
LOCAL_OPERATOR_USERNAME = "local-operator"
LOCAL_OPERATOR_DISPLAY_NAME = "Local operator"
LOCAL_OPERATOR_ROLE = "admin"


@dataclass
class UIAppContext:
    session_secret: str = UI_SESSION_SECRET
    results_dir: Path = RESULTS_DIR
    reports_dir: Path = REPORTS_DIR
    logs_dir: Path = LOGS_DIR
    tz_name: str = LIVE_SESSION_TIMEZONE
    tail_lines_default: int = UI_TAIL_LINES_DEFAULT
    control_rate_limit: int = UI_CONTROL_RATE_LIMIT
    controls_enabled: bool = UI_ENABLE_CONTROLS
    control_use_sudo: bool = UI_CONTROL_USE_SUDO
    session_max_age_secs: int = UI_SESSION_MAX_AGE_SECS
    audit_log_path: Path = UI_AUDIT_LOG_PATH
    target_service: str = UI_TARGET_SERVICE
    status_runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None
    journal_runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None
    control_runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None
    rate_limiter: InMemoryRateLimiter = field(default_factory=InMemoryRateLimiter)
    analyst_service: AnalystService | None = None
    execution_service: TradingExecutionService | None = None
    cors_allowed_origins: tuple[str, ...] = UI_CORS_ALLOWED_ORIGINS


class AnalystRunRequest(BaseModel):
    symbol: str = "ALL"
    question: str | None = None
    validate_alert_id: str | None = None
    explain_alert_id: str | None = None
    latest_news: bool = False
    market_snapshot: dict[str, Any] | None = None


class OrderAdviceRequest(BaseModel):
    symbol: str = "BTCUSDT"
    instruction: str


class OrderActionRequest(BaseModel):
    suggestion_id: str


def _client_identity(request: Request) -> str:
    host = request.client.host if request.client else "unknown"
    return f"{host}:{request.url.path}"


def _write_audit(ctx: UIAppContext, event: str, *, outcome: str, request: Request, details: dict[str, Any] | None = None) -> None:
    payload = {"client_host": request.client.host if request.client else "unknown"}
    if details:
        payload.update(details)
    append_ui_audit_log(event, outcome=outcome, details=payload, audit_log_path=ctx.audit_log_path)


def _ensure_local_session(request: Request) -> None:
    if request.session.get("authenticated"):
        if not request.session.get("csrf_token"):
            request.session["csrf_token"] = mint_csrf_token()
        return
    request.session.clear()
    request.session["authenticated"] = True
    request.session["username"] = LOCAL_OPERATOR_USERNAME
    request.session["role"] = LOCAL_OPERATOR_ROLE
    request.session["auth_method"] = "local"
    request.session["display_name"] = LOCAL_OPERATOR_DISPLAY_NAME
    request.session["csrf_token"] = mint_csrf_token()


def _ensure_csrf(request: Request) -> str:
    _ensure_local_session(request)
    return str(request.session["csrf_token"])


async def _validate_csrf(request: Request) -> None:
    _ensure_local_session(request)
    expected = request.session.get("csrf_token")
    if not expected:
        raise HTTPException(status_code=403, detail="Missing CSRF token.")
    supplied = request.headers.get("x-csrf-token")
    if supplied is None:
        form = await request.form()
        supplied = str(form.get("csrf_token", ""))
    if not secrets.compare_digest(str(expected), str(supplied)):
        raise HTTPException(status_code=403, detail="Invalid CSRF token.")


def _base_template_context(request: Request, ctx: UIAppContext) -> dict[str, Any]:
    _ensure_local_session(request)
    return {
        "request": request,
        "csrf_token": _ensure_csrf(request),
        "controls_enabled": ctx.controls_enabled,
        "strategy_nav_note": STRATEGY_NAV_NOTE,
        "session_user": request.session.get("display_name") or request.session.get("username", ""),
        "session_role": str(request.session.get("role", LOCAL_OPERATOR_ROLE)),
        "is_admin": True,
    }


def _render_template(
    request: Request,
    template_name: str,
    context: dict[str, Any],
    *,
    status_code: int = 200,
) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(request, template_name, context, status_code=status_code)


def _cadence_seconds(value: str) -> int:
    text = str(value or "15m").strip().lower()
    try:
        if text.endswith("s"):
            return max(1, int(text[:-1]))
        if text.endswith("m"):
            return max(1, int(text[:-1]) * 60)
        if text.endswith("h"):
            return max(1, int(text[:-1]) * 3600)
    except ValueError:
        pass
    return 900


def _scheduler_result_summary(results: list[dict[str, Any]]) -> list[dict[str, str]]:
    keys = ("status", "symbol", "stage", "error", "event_type", "created_at_utc")
    return [
        {key: str(result.get(key, "")) for key in keys if result.get(key) not in (None, "")}
        for result in results
    ]


def create_app(ctx: UIAppContext | None = None) -> FastAPI:
    context = ctx or UIAppContext()
    if context.analyst_service is None:
        context.analyst_service = create_default_analyst_service()
    if context.execution_service is None:
        context.execution_service = create_default_execution_service(analyst_service=context.analyst_service)
    run_embedded_scanner = ctx is None and context.analyst_service.enabled

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        scanner_tasks: list[asyncio.Task[None]] = []
        if run_embedded_scanner:
            scanner = create_default_scanner(service=context.analyst_service)
            app.state.analyst_scanner = scanner

            async def periodic_loop(worker: Callable[[], list[dict]], interval_secs: int) -> None:
                while True:
                    started = asyncio.get_running_loop().time()
                    try:
                        await asyncio.to_thread(worker)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        # Scanner failures are reflected by a stale screening
                        # heartbeat; the API must remain available for manual use.
                        pass
                    elapsed = asyncio.get_running_loop().time() - started
                    await asyncio.sleep(max(0.0, interval_secs - elapsed))

            scanner_tasks = [
                asyncio.create_task(
                    periodic_loop(scanner.run_once, max(1, int(scanner.scan_interval_secs))),
                    name="analyst-timeframe-orchestrator",
                )
            ]
            app.state.analyst_scheduler_tasks = {task.get_name(): task for task in scanner_tasks}
        try:
            yield
        finally:
            for task in scanner_tasks:
                task.cancel()
            for task in scanner_tasks:
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    app = FastAPI(title="Trading Bot Private UI", lifespan=lifespan)
    app.state.analyst_scheduler_tasks = {}
    app.state.analyst_scanner = None
    app.state.ctx = context
    app.add_middleware(
        SessionMiddleware,
        secret_key=context.session_secret,
        same_site="strict",
        https_only=False,
        max_age=context.session_max_age_secs,
    )
    if context.cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(context.cors_allowed_origins),
            allow_credentials=True,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["*"],
        )
    app.mount("/static", StaticFiles(directory=str(UI_ROOT / "static")), name="static")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request) -> Response:
        payload = build_dashboard_payload(
            tz_name=context.tz_name,
            results_dir=context.results_dir,
            reports_dir=context.reports_dir,
            service_name=context.target_service,
            status_runner=context.status_runner,
        )
        template_ctx = _base_template_context(request, context)
        template_ctx.update(payload)
        return _render_template(request, "dashboard.html", template_ctx)

    @app.get("/reports", response_class=HTMLResponse)
    async def reports_page(
        request: Request,
        mode: str = "date",
        date: str | None = None,
        hours: float | None = None,
    ) -> Response:
        payload = build_report_payload(
            mode=mode,
            tz_name=context.tz_name,
            report_date=date,
            last_hours=hours,
            results_dir=context.results_dir,
            reports_dir=context.reports_dir,
        )
        template_ctx = _base_template_context(request, context)
        template_ctx.update(payload)
        template_ctx.update({"mode": mode, "selected_date": date, "hours": hours})
        return _render_template(request, "reports.html", template_ctx)

    @app.get("/history", response_class=HTMLResponse)
    async def history_page(request: Request) -> Response:
        payload = build_history_payload(tz_name=context.tz_name, results_dir=context.results_dir)
        template_ctx = _base_template_context(request, context)
        template_ctx.update(payload)
        return _render_template(request, "history.html", template_ctx)

    @app.get("/logs", response_class=HTMLResponse)
    async def logs_page(request: Request, source: str = "stderr", lines: int | None = None) -> Response:
        try:
            log_payload = read_log_source(
                source,
                lines=lines or context.tail_lines_default,
                logs_dir=context.logs_dir,
                journal_runner=context.journal_runner,
                service_name=context.target_service,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        template_ctx = _base_template_context(request, context)
        template_ctx.update({"log_payload": log_payload, "selected_source": source, "lines": lines or context.tail_lines_default})
        return _render_template(request, "logs.html", template_ctx)

    @app.get("/reports/file/{report_date}/{filename}")
    async def report_file(request: Request, report_date: str, filename: str) -> Response:
        try:
            path = safe_compact_report_path(report_date, filename, reports_dir=context.reports_dir)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return FileResponse(path)

    @app.get("/api/status")
    async def api_status(request: Request) -> JSONResponse:
        _ensure_local_session(request)
        return JSONResponse(
            build_dashboard_payload(
                tz_name=context.tz_name,
                results_dir=context.results_dir,
                reports_dir=context.reports_dir,
                service_name=context.target_service,
                status_runner=context.status_runner,
            )
        )

    @app.get("/api/report")
    async def api_report(
        request: Request,
        mode: str = "date",
        date: str | None = None,
        hours: float | None = None,
    ) -> JSONResponse:
        _ensure_local_session(request)
        return JSONResponse(
            build_report_payload(
                mode=mode,
                tz_name=context.tz_name,
                report_date=date,
                last_hours=hours,
                results_dir=context.results_dir,
                reports_dir=context.reports_dir,
            )
        )

    @app.get("/api/history")
    async def api_history(request: Request) -> JSONResponse:
        _ensure_local_session(request)
        return JSONResponse(build_history_payload(tz_name=context.tz_name, results_dir=context.results_dir))

    @app.get("/api/logs")
    async def api_logs(request: Request, source: str = "stderr", lines: int | None = None) -> JSONResponse:
        _ensure_local_session(request)
        try:
            payload = read_log_source(
                source,
                lines=lines or context.tail_lines_default,
                logs_dir=context.logs_dir,
                journal_runner=context.journal_runner,
                service_name=context.target_service,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(payload)

    @app.get("/api/analyst/status")
    async def api_analyst_status(request: Request) -> JSONResponse:
        _ensure_local_session(request)
        payload = context.analyst_service.status().to_dict()
        scheduler_tasks = getattr(app.state, "analyst_scheduler_tasks", {})
        scanner = getattr(app.state, "analyst_scanner", None)
        payload["scheduler"] = {
            "enabled": run_embedded_scanner,
            "poll_interval_secs": getattr(scanner, "scan_interval_secs", None),
            "candle_aligned_timeframes": ["1m", "15m", "1h", "4h"],
            "last_completed_at": getattr(scanner, "last_screening_completed_at", ""),
            "last_results": _scheduler_result_summary(getattr(scanner, "last_screening_results", [])),
            "stage_by_symbol": getattr(scanner, "screening_stage_by_symbol", {}),
            "tasks": {
                name: {
                    "running": not task.done(),
                    "cancelled": task.cancelled(),
                    "error": (
                        type(task.exception()).__name__
                        if task.done() and not task.cancelled() and task.exception() is not None
                        else ""
                    ),
                }
                for name, task in scheduler_tasks.items()
            },
        }
        return JSONResponse(payload)

    @app.post("/api/analyst/run")
    async def api_analyst_run(request: Request, payload: AnalystRunRequest) -> JSONResponse:
        _ensure_local_session(request)
        if payload.explain_alert_id:
            event = context.analyst_service.explain(alert_id=payload.explain_alert_id)
        elif payload.latest_news:
            event = context.analyst_service.latest_news(symbol=payload.symbol)
        elif payload.validate_alert_id:
            event = context.analyst_service.validate(
                alert_id=payload.validate_alert_id,
                symbol=payload.symbol,
                scope="interactive",
            )
        elif payload.question:
            event = context.analyst_service.ask(
                question=payload.question,
                symbol=payload.symbol,
                scope="interactive",
            )
        else:
            event = context.analyst_service.run_update(
                symbol=payload.symbol,
                market_snapshot=payload.market_snapshot,
                scope="interactive",
            )
        return JSONResponse(event.to_public_dict())

    @app.get("/api/analyst/events")
    async def api_analyst_events(request: Request, limit: int | None = None) -> JSONResponse:
        _ensure_local_session(request)
        return JSONResponse({"events": context.analyst_service.events(limit=limit)})

    @app.get("/api/analyst/signals")
    async def api_analyst_signals(request: Request, limit: int | None = None) -> JSONResponse:
        _ensure_local_session(request)
        return JSONResponse({"signals": context.analyst_service.signals(limit=limit)})

    @app.get("/api/analyst/budget")
    async def api_analyst_budget(request: Request) -> JSONResponse:
        _ensure_local_session(request)
        return JSONResponse(context.analyst_service.budget.snapshot())

    @app.get("/api/session/csrf")
    async def api_csrf(request: Request) -> JSONResponse:
        return JSONResponse({"csrf_token": _ensure_csrf(request)})

    @app.get("/api/orders/suggestions")
    async def api_order_suggestions(request: Request, limit: int = 100) -> JSONResponse:
        _ensure_local_session(request)
        return JSONResponse({"suggestions": context.execution_service.suggestion_store.list(limit=limit)})

    @app.post("/api/orders/advice")
    async def api_order_advice(request: Request, payload: OrderAdviceRequest) -> JSONResponse:
        await _validate_csrf(request)
        event = await asyncio.to_thread(
            context.execution_service.suggest_order,
            symbol=payload.symbol,
            instruction=payload.instruction,
            requested_by=LOCAL_OPERATOR_USERNAME,
        )
        return JSONResponse(event.to_public_dict())

    @app.post("/api/orders/confirm")
    async def api_order_confirm(request: Request, payload: OrderActionRequest) -> JSONResponse:
        await _validate_csrf(request)
        event = await asyncio.to_thread(
            context.execution_service.confirm_order,
            suggestion_id=payload.suggestion_id,
            requested_by=LOCAL_OPERATOR_USERNAME,
        )
        return JSONResponse(event.to_public_dict())

    @app.post("/api/orders/reject")
    async def api_order_reject(request: Request, payload: OrderActionRequest) -> JSONResponse:
        await _validate_csrf(request)
        event = context.execution_service.reject_order(
            suggestion_id=payload.suggestion_id, requested_by=LOCAL_OPERATOR_USERNAME
        )
        return JSONResponse(event.to_public_dict())

    @app.get("/api/market/candles")
    async def api_market_candles(
        request: Request,
        symbol: str = "BTCUSDT",
        interval: str = "1h",
        limit: int = 500,
    ) -> JSONResponse:
        _ensure_local_session(request)
        try:
            candles = fetch_public_candles(symbol=symbol, interval=interval, limit=limit)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"OKX public candle fetch failed: {exc}") from exc
        return JSONResponse(
            {
                "symbol": symbol.upper(),
                "interval": interval,
                "source": "okx_public",
                "candles": candles,
            }
        )

    @app.websocket("/ws/analyst")
    async def ws_analyst(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            await websocket.send_json({"type": "analyst_events", "events": context.analyst_service.events()})
            while True:
                try:
                    await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
                except TimeoutError:
                    await websocket.send_json({"type": "analyst_events", "events": context.analyst_service.events()})
        except WebSocketDisconnect:
            return

    @app.post("/api/control/{action}")
    async def api_control(action: str, request: Request) -> JSONResponse:
        _ensure_local_session(request)
        await _validate_csrf(request)
        if not context.controls_enabled:
            _write_audit(context, "control", outcome="disabled", request=request, details={"action": action})
            raise HTTPException(status_code=403, detail="Controls are disabled.")
        if not context.rate_limiter.allow(f"control:{_client_identity(request)}", context.control_rate_limit):
            _write_audit(context, "control", outcome="rate_limited", request=request, details={"action": action})
            raise HTTPException(status_code=429, detail="Too many control attempts.")
        try:
            command = build_control_command(
                action,
                service_name=context.target_service,
                use_sudo=context.control_use_sudo,
            )
        except ValueError as exc:
            _write_audit(context, "control", outcome="invalid_action", request=request, details={"action": action})
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        result = run_control_command(
            action,
            runner=context.control_runner,
            service_name=context.target_service,
            use_sudo=context.control_use_sudo,
        )
        _write_audit(
            context,
            "control",
            outcome="success" if result["returncode"] == 0 else "failure",
            request=request,
            details={"action": action, "command": command, "returncode": result["returncode"]},
        )
        return JSONResponse(result, status_code=200 if result["returncode"] == 0 else 500)

    return app


app = create_app()
