"""
FastAPI app for the private trading-bot UI.
"""

from __future__ import annotations

import secrets
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from config import (
    BASE_DIR,
    LIVE_SESSION_TIMEZONE,
    LOGS_DIR,
    REPORTS_DIR,
    RESULTS_DIR,
    UI_AUDIT_LOG_PATH,
    UI_CONTROL_RATE_LIMIT,
    UI_ENABLE_CONTROLS,
    UI_LOGIN_RATE_LIMIT,
    UI_PASSWORD,
    UI_SESSION_MAX_AGE_SECS,
    UI_SESSION_SECRET,
    UI_TAIL_LINES_DEFAULT,
    UI_TARGET_SERVICE,
    UI_USERNAME,
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

UI_ROOT = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(UI_ROOT / "templates"))


@dataclass
class UIAppContext:
    username: str = UI_USERNAME
    password: str = UI_PASSWORD
    session_secret: str = UI_SESSION_SECRET
    results_dir: Path = RESULTS_DIR
    reports_dir: Path = REPORTS_DIR
    logs_dir: Path = LOGS_DIR
    tz_name: str = LIVE_SESSION_TIMEZONE
    tail_lines_default: int = UI_TAIL_LINES_DEFAULT
    login_rate_limit: int = UI_LOGIN_RATE_LIMIT
    control_rate_limit: int = UI_CONTROL_RATE_LIMIT
    controls_enabled: bool = UI_ENABLE_CONTROLS
    session_max_age_secs: int = UI_SESSION_MAX_AGE_SECS
    audit_log_path: Path = UI_AUDIT_LOG_PATH
    target_service: str = UI_TARGET_SERVICE
    status_runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None
    journal_runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None
    control_runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None
    rate_limiter: InMemoryRateLimiter = field(default_factory=InMemoryRateLimiter)


def _client_identity(request: Request) -> str:
    host = request.client.host if request.client else "unknown"
    return f"{host}:{request.url.path}"


def _write_audit(ctx: UIAppContext, event: str, *, outcome: str, request: Request, details: dict[str, Any] | None = None) -> None:
    payload = {"client_host": request.client.host if request.client else "unknown"}
    if details:
        payload.update(details)
    append_ui_audit_log(event, outcome=outcome, details=payload, audit_log_path=ctx.audit_log_path)


def _ensure_csrf(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = mint_csrf_token()
        request.session["csrf_token"] = token
    return token


def _require_page_auth(request: Request, ctx: UIAppContext) -> Response | None:
    if request.session.get("authenticated"):
        return None
    _write_audit(ctx, "page_access", outcome="denied", request=request, details={"path": str(request.url.path)})
    return RedirectResponse(url="/login", status_code=303)


def _require_api_auth(request: Request, ctx: UIAppContext) -> None:
    if request.session.get("authenticated"):
        return
    _write_audit(ctx, "api_access", outcome="denied", request=request, details={"path": str(request.url.path)})
    raise HTTPException(status_code=401, detail="Authentication required.")


async def _validate_csrf(request: Request) -> None:
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
    return {
        "request": request,
        "csrf_token": _ensure_csrf(request),
        "controls_enabled": ctx.controls_enabled,
        "strategy_nav_note": STRATEGY_NAV_NOTE,
    }


def _render_template(
    request: Request,
    template_name: str,
    context: dict[str, Any],
    *,
    status_code: int = 200,
) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(request, template_name, context, status_code=status_code)


def create_app(ctx: UIAppContext | None = None) -> FastAPI:
    app = FastAPI(title="Trading Bot Private UI")
    context = ctx or UIAppContext()
    app.state.ctx = context
    app.add_middleware(
        SessionMiddleware,
        secret_key=context.session_secret,
        same_site="strict",
        https_only=False,
        max_age=context.session_max_age_secs,
    )
    app.mount("/static", StaticFiles(directory=str(UI_ROOT / "static")), name="static")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request) -> HTMLResponse:
        if request.session.get("authenticated"):
            return RedirectResponse(url="/", status_code=303)
        template_ctx = _base_template_context(request, context)
        template_ctx.update({"error": ""})
        return _render_template(request, "login.html", template_ctx)

    @app.post("/login", response_class=HTMLResponse)
    async def login(
        request: Request,
        username: str = Form(""),
        password: str = Form(""),
    ) -> Response:
        if not context.rate_limiter.allow(f"login:{_client_identity(request)}", context.login_rate_limit):
            _write_audit(context, "login", outcome="rate_limited", request=request)
            return _render_template(
                request,
                "login.html",
                {**_base_template_context(request, context), "error": "Too many login attempts."},
                status_code=429,
            )
        try:
            await _validate_csrf(request)
        except HTTPException:
            _write_audit(context, "login", outcome="csrf_failed", request=request)
            raise
        if not context.username or not context.password:
            _write_audit(context, "login", outcome="misconfigured", request=request)
            return _render_template(
                request,
                "login.html",
                {**_base_template_context(request, context), "error": "UI credentials are not configured."},
                status_code=503,
            )
        valid = secrets.compare_digest(username, context.username) and secrets.compare_digest(password, context.password)
        if not valid:
            _write_audit(context, "login", outcome="failed", request=request, details={"username": username})
            return _render_template(
                request,
                "login.html",
                {**_base_template_context(request, context), "error": "Invalid credentials."},
                status_code=401,
            )
        request.session.clear()
        request.session["authenticated"] = True
        request.session["username"] = context.username
        request.session["csrf_token"] = mint_csrf_token()
        _write_audit(context, "login", outcome="success", request=request, details={"username": username})
        return RedirectResponse(url="/", status_code=303)

    @app.post("/logout")
    async def logout(request: Request) -> Response:
        _require_api_auth(request, context)
        await _validate_csrf(request)
        _write_audit(context, "logout", outcome="success", request=request)
        request.session.clear()
        return RedirectResponse(url="/login", status_code=303)

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request) -> Response:
        auth_redirect = _require_page_auth(request, context)
        if auth_redirect:
            return auth_redirect
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
        auth_redirect = _require_page_auth(request, context)
        if auth_redirect:
            return auth_redirect
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
        auth_redirect = _require_page_auth(request, context)
        if auth_redirect:
            return auth_redirect
        payload = build_history_payload(tz_name=context.tz_name, results_dir=context.results_dir)
        template_ctx = _base_template_context(request, context)
        template_ctx.update(payload)
        return _render_template(request, "history.html", template_ctx)

    @app.get("/logs", response_class=HTMLResponse)
    async def logs_page(request: Request, source: str = "stderr", lines: int | None = None) -> Response:
        auth_redirect = _require_page_auth(request, context)
        if auth_redirect:
            return auth_redirect
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
        auth_redirect = _require_page_auth(request, context)
        if auth_redirect:
            return auth_redirect
        try:
            path = safe_compact_report_path(report_date, filename, reports_dir=context.reports_dir)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return FileResponse(path)

    @app.get("/api/status")
    async def api_status(request: Request) -> JSONResponse:
        _require_api_auth(request, context)
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
        _require_api_auth(request, context)
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
        _require_api_auth(request, context)
        return JSONResponse(build_history_payload(tz_name=context.tz_name, results_dir=context.results_dir))

    @app.get("/api/logs")
    async def api_logs(request: Request, source: str = "stderr", lines: int | None = None) -> JSONResponse:
        _require_api_auth(request, context)
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

    @app.post("/api/control/{action}")
    async def api_control(action: str, request: Request) -> JSONResponse:
        _require_api_auth(request, context)
        await _validate_csrf(request)
        if not context.controls_enabled:
            _write_audit(context, "control", outcome="disabled", request=request, details={"action": action})
            raise HTTPException(status_code=403, detail="Controls are disabled.")
        if not context.rate_limiter.allow(f"control:{_client_identity(request)}", context.control_rate_limit):
            _write_audit(context, "control", outcome="rate_limited", request=request, details={"action": action})
            raise HTTPException(status_code=429, detail="Too many control attempts.")
        try:
            command = build_control_command(action, service_name=context.target_service)
        except ValueError as exc:
            _write_audit(context, "control", outcome="invalid_action", request=request, details={"action": action})
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        result = run_control_command(action, runner=context.control_runner, service_name=context.target_service)
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
