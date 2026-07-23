"""Fail-closed RL evidence envelope for analyst-only LLM context."""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RL_EVIDENCE_SCHEMA_VERSION = "rl_evidence.v1"
RL_EVIDENCE_STATES = {"VERIFIED", "CAUTION", "ABSTAIN"}
EXECUTABLE_EVIDENCE_KEYS = {
    "allocation",
    "amount",
    "exchange_command",
    "leverage",
    "order",
    "order_id",
    "position_size",
    "quantity",
    "qty",
    "size",
    "target_allocation",
    "target_weight",
    "target_weights",
    "weights",
}


@dataclass
class RLEvidenceEnvelope:
    schema_version: str = RL_EVIDENCE_SCHEMA_VERSION
    status: str = "ABSTAIN"
    as_of_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    horizon: str = "research_backtest"
    summary: str = "RL evidence is unavailable."
    reasons: list[str] = field(default_factory=list)
    metrics: dict[str, float | str | None] = field(default_factory=dict)
    uncertainty: dict[str, Any] = field(default_factory=dict)
    calibration: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    llm_instructions: list[str] = field(default_factory=lambda: [
        "Use this as non-executable evidence only.",
        "Treat ABSTAIN as no RL opinion.",
        "Do not infer quantities, leverage, orders, or target allocations from this envelope.",
        "Do not upgrade RL reliability using LLM self-reported confidence.",
    ])

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = _normalize_status(data.get("status"))
        data["reasons"] = [str(item) for item in data.get("reasons", []) if str(item).strip()]
        return _sanitize_payload(data)


def abstain_envelope(
    reason: str | list[str],
    *,
    source_path: Path | None = None,
    now: datetime | None = None,
) -> RLEvidenceEnvelope:
    reasons = [reason] if isinstance(reason, str) else list(reason)
    provenance: dict[str, Any] = {}
    if source_path is not None:
        provenance["source_path"] = str(source_path)
    return RLEvidenceEnvelope(
        status="ABSTAIN",
        as_of_utc=(now or datetime.now(timezone.utc)).isoformat(),
        summary="RL evidence is withheld from analyst use.",
        reasons=[str(item) for item in reasons if str(item).strip()],
        provenance=provenance,
    )


def load_rl_evidence(
    path: Path,
    *,
    now: datetime | None = None,
    max_age_secs: int = 86_400,
) -> dict[str, Any]:
    """Load and normalize a JSON evidence artifact, failing closed."""
    source_path = Path(path)
    current = now or datetime.now(timezone.utc)
    if not source_path.exists():
        return abstain_envelope("missing_evidence_artifact", source_path=source_path, now=current).to_dict()

    try:
        raw = json.loads(source_path.read_text(encoding="utf-8"))
    except Exception:
        return abstain_envelope("malformed_evidence_artifact", source_path=source_path, now=current).to_dict()

    if not isinstance(raw, dict):
        return abstain_envelope("malformed_evidence_artifact", source_path=source_path, now=current).to_dict()

    envelope = _sanitize_payload(raw)
    envelope["schema_version"] = str(envelope.get("schema_version") or RL_EVIDENCE_SCHEMA_VERSION)
    envelope["status"] = _normalize_status(envelope.get("status"))
    envelope["reasons"] = [str(item) for item in envelope.get("reasons", []) if str(item).strip()]
    envelope.setdefault("provenance", {})
    if isinstance(envelope["provenance"], dict):
        envelope["provenance"].setdefault("source_path", str(source_path))
    envelope["llm_instructions"] = RLEvidenceEnvelope().llm_instructions

    age_reason = _age_failure_reason(envelope.get("as_of_utc"), now=current, max_age_secs=max_age_secs)
    if age_reason:
        envelope["status"] = "ABSTAIN"
        envelope["reasons"].append(age_reason)

    expiry_reason = _promotion_expiry_failure_reason(envelope, now=current)
    if envelope["status"] == "VERIFIED" and expiry_reason:
        envelope["status"] = "ABSTAIN"
        envelope["reasons"].append(expiry_reason)

    if envelope["status"] not in RL_EVIDENCE_STATES:
        envelope["status"] = "ABSTAIN"
        envelope["reasons"].append("unknown_evidence_status")

    if envelope["status"] == "ABSTAIN" and not envelope["reasons"]:
        envelope["reasons"].append("evidence_abstained")

    return envelope


def build_evidence_from_backtest(
    *,
    metrics_path: Path,
    metadata_path: Path | None = None,
    statistical_report_path: Path | None = None,
    output_path: Path | None = None,
    now: datetime | None = None,
    promoted: bool = False,
    promotion_expires_utc: str = "",
    causal_integrity_passed: bool = False,
    statistical_gates_passed: bool = False,
    calibration_passed: bool = False,
    prospective_shadow_passed: bool = False,
    horizon: str = "research_backtest",
) -> dict[str, Any]:
    """Build a non-executable evidence envelope from a backtest metrics CSV."""
    current = now or datetime.now(timezone.utc)
    metrics_file = Path(metrics_path)
    metrics = _read_metrics_csv(metrics_file)
    metadata = _read_json_file(metadata_path) if metadata_path else {}
    statistical_report = _read_json_file(statistical_report_path) if statistical_report_path else {}
    reasons = _gate_reasons(
        promoted=promoted,
        promotion_expires_utc=promotion_expires_utc,
        causal_integrity_passed=causal_integrity_passed,
        statistical_gates_passed=statistical_gates_passed,
        calibration_passed=calibration_passed,
        prospective_shadow_passed=prospective_shadow_passed,
        now=current,
    )
    status = "VERIFIED" if not reasons else "ABSTAIN"
    summary = (
        "RL evidence passed configured promotion gates."
        if status == "VERIFIED"
        else "RL evidence is withheld until promotion, statistical, calibration, and prospective gates pass."
    )
    provenance = {
            "metrics_path": str(metrics_file),
            "metrics_sha256": _sha256_file(metrics_file) if metrics_file.exists() else "",
            "metadata": metadata,
            "statistical_report_path": str(statistical_report_path) if statistical_report_path else "",
            "statistical_report_sha256": _sha256_file(Path(statistical_report_path))
            if statistical_report_path and Path(statistical_report_path).exists()
            else "",
            "promotion_expires_utc": promotion_expires_utc,
            "gates": {
                "promoted": promoted,
            "causal_integrity_passed": causal_integrity_passed,
            "statistical_gates_passed": statistical_gates_passed,
            "calibration_passed": calibration_passed,
            "prospective_shadow_passed": prospective_shadow_passed,
        },
    }
    envelope = RLEvidenceEnvelope(
        status=status,
        as_of_utc=current.isoformat(),
        horizon=horizon,
        summary=summary,
        reasons=reasons,
        metrics=_public_metrics(metrics),
        uncertainty=_public_uncertainty(statistical_report),
        calibration={
            "conformal_interval_available": False,
            "trailing_coverage_available": False,
            "status": "missing" if not calibration_passed else "passed",
        },
        provenance=provenance,
    ).to_dict()
    if output_path is not None:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(envelope, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return envelope


def _gate_reasons(
    *,
    promoted: bool,
    promotion_expires_utc: str,
    causal_integrity_passed: bool,
    statistical_gates_passed: bool,
    calibration_passed: bool,
    prospective_shadow_passed: bool,
    now: datetime,
) -> list[str]:
    reasons: list[str] = []
    if not promoted:
        reasons.append("promotion_status_missing")
    if not promotion_expires_utc:
        reasons.append("promotion_expiry_missing")
    else:
        try:
            if _parse_utc(promotion_expires_utc) <= now:
                reasons.append("promotion_status_expired")
        except Exception:
            reasons.append("promotion_expiry_invalid")
    if not causal_integrity_passed:
        reasons.append("causal_integrity_gate_missing")
    if not statistical_gates_passed:
        reasons.append("statistical_gates_missing")
    if not calibration_passed:
        reasons.append("calibration_gate_missing")
    if not prospective_shadow_passed:
        reasons.append("prospective_shadow_gate_missing")
    return reasons


def _read_metrics_csv(path: Path) -> dict[str, float | str | None]:
    if not path.exists():
        return {}
    metrics: dict[str, float | str | None] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            key = str(row.get("") or row.get("metric") or row.get("name") or "").strip()
            if not key:
                continue
            metrics[key] = _parse_scalar(row.get("value"))
    return metrics


def _read_json_file(path: Path | None) -> dict[str, Any]:
    if path is None or not Path(path).exists():
        return {}
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _public_metrics(metrics: dict[str, float | str | None]) -> dict[str, float | str | None]:
    allowed = {
        "total_return_pct",
        "annualised_return_pct",
        "max_drawdown_pct",
        "sharpe_ratio",
        "sortino_ratio",
        "calmar_ratio",
        "profit_factor",
        "recovery_factor",
        "cvar_95_pct",
        "cvar_99_pct",
        "time_in_market_pct",
        "total_trades_count",
        "trade_count",
    }
    return {key: metrics.get(key) for key in sorted(allowed) if key in metrics}


def _public_uncertainty(statistical_report: dict[str, Any]) -> dict[str, Any]:
    uncertainty: dict[str, Any] = {
        "bootstrap_interval_available": False,
        "pbo_available": False,
        "dsr_available": False,
        "probability_of_improvement_available": False,
    }
    if not statistical_report:
        return uncertainty

    strategy = statistical_report.get("strategy", {})
    baselines = statistical_report.get("baselines", {})
    strategy_ci = strategy.get("bootstrap_ci", {}) if isinstance(strategy, dict) else {}
    probability_by_baseline: dict[str, Any] = {}
    if isinstance(baselines, dict):
        for baseline_name, details in baselines.items():
            if not isinstance(details, dict):
                continue
            probabilities = details.get("probability_strategy_beats_baseline")
            if isinstance(probabilities, dict):
                probability_by_baseline[str(baseline_name)] = {
                    metric_name: probabilities.get(metric_name)
                    for metric_name in ("total_return_pct", "sharpe_ratio", "max_drawdown_pct")
                    if metric_name in probabilities
                }

    uncertainty.update(
        {
            "bootstrap_interval_available": bool(strategy_ci),
            "probability_of_improvement_available": bool(probability_by_baseline),
            "method": statistical_report.get("method", ""),
            "gate_status": statistical_report.get("gate_status", {}),
            "strategy_ci": {
                metric_name: strategy_ci.get(metric_name)
                for metric_name in ("total_return_pct", "sharpe_ratio", "max_drawdown_pct")
                if metric_name in strategy_ci
            },
            "probability_strategy_beats_baseline": probability_by_baseline,
            "caveat": "Same-path bootstrap diagnostics are informational and do not make RL agent-trustworthy without the remaining promotion gates.",
        }
    )
    return uncertainty


def build_evidence_from_promotion_gate(
    *,
    promotion_gate_path: Path,
    output_path: Path | None = None,
    now: datetime | None = None,
    promoted: bool = False,
    promotion_expires_utc: str = "",
    causal_integrity_passed: bool = False,
    statistical_gates_passed: bool = False,
    calibration_passed: bool = False,
    prospective_shadow_passed: bool = False,
    horizon: str = "historical_multiseed_backtest",
) -> dict[str, Any]:
    """Build a single analyst-safe evidence envelope from a promotion-gate report.

    This is the aggregate handoff artifact intended for LLM analyst context. It
    deliberately fails closed unless the machine-readable promotion gate is
    already promoted and the non-backtest reliability gates are explicitly
    asserted with a future expiry.
    """
    current = now or datetime.now(timezone.utc)
    gate_file = Path(promotion_gate_path)
    report = _read_json_file(gate_file)
    reasons = _promotion_gate_report_reasons(report)
    reasons.extend(
        _gate_reasons(
            promoted=promoted,
            promotion_expires_utc=promotion_expires_utc,
            causal_integrity_passed=causal_integrity_passed,
            statistical_gates_passed=statistical_gates_passed,
            calibration_passed=calibration_passed,
            prospective_shadow_passed=prospective_shadow_passed,
            now=current,
        )
    )
    status = "VERIFIED" if not reasons else "ABSTAIN"
    candidate_label = str(report.get("candidate_label") or gate_file.stem)
    summary = (
        f"RL candidate {candidate_label} passed aggregate promotion and external reliability gates."
        if status == "VERIFIED"
        else f"RL candidate {candidate_label} is withheld from analyst use until promotion, statistical, calibration, and prospective gates pass."
    )
    provenance = {
        "promotion_gate_report_path": str(gate_file),
        "promotion_gate_report_sha256": _sha256_file(gate_file) if gate_file.exists() else "",
        "candidate_label": candidate_label,
        "promotion_gate_status": report.get("status", "missing"),
        "promotion_gate_llm_evidence_status": report.get("llm_evidence_status", "missing"),
        "promotion_gate_blocking_failures": report.get("blocking_failures", []),
        "promotion_gate_provenance": report.get("provenance", {}),
        "promotion_expires_utc": promotion_expires_utc,
        "gates": {
            "promoted": promoted,
            "promotion_gate_promoted": str(report.get("status", "")).upper() == "PROMOTED",
            "promotion_gate_llm_evidence_verified": str(report.get("llm_evidence_status", "")).upper() == "VERIFIED",
            "causal_integrity_passed": causal_integrity_passed,
            "statistical_gates_passed": statistical_gates_passed,
            "calibration_passed": calibration_passed,
            "prospective_shadow_passed": prospective_shadow_passed,
        },
    }
    envelope = RLEvidenceEnvelope(
        status=status,
        as_of_utc=current.isoformat(),
        horizon=horizon,
        summary=summary,
        reasons=reasons,
        metrics=_public_promotion_gate_metrics(report),
        uncertainty=_public_promotion_gate_uncertainty(report),
        calibration={
            "conformal_interval_available": False,
            "trailing_coverage_available": False,
            "status": "passed" if calibration_passed else "missing",
        },
        provenance=provenance,
    ).to_dict()
    if output_path is not None:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(envelope, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return envelope


def _promotion_gate_report_reasons(report: dict[str, Any]) -> list[str]:
    if not report:
        return ["promotion_gate_report_missing"]

    reasons: list[str] = []
    if str(report.get("status", "")).upper() != "PROMOTED":
        reasons.append("promotion_gate_not_promoted")
    if str(report.get("llm_evidence_status", "")).upper() != "VERIFIED":
        reasons.append("promotion_gate_llm_evidence_not_verified")
    blocking_failures = report.get("blocking_failures", [])
    if isinstance(blocking_failures, list) and blocking_failures:
        reasons.append("promotion_gate_blocking_failures_present")
    return reasons


def _public_promotion_gate_metrics(report: dict[str, Any]) -> dict[str, float | str | None]:
    aggregate = report.get("aggregate", {}) if isinstance(report, dict) else {}
    profiles = aggregate.get("profiles", {}) if isinstance(aggregate, dict) else {}
    thresholds = (
        report.get("provenance", {}).get("thresholds", {})
        if isinstance(report.get("provenance", {}), dict)
        else {}
    )
    operating_profile = str(thresholds.get("operating_profile") or "live_like_2x")
    severe_profile = str(thresholds.get("severe_profile") or "live_like_3x")
    metrics: dict[str, float | str | None] = {
        "candidate_label": str(report.get("candidate_label") or "") if isinstance(report, dict) else "",
        "seed_count": _parse_scalar(aggregate.get("seed_count")) if isinstance(aggregate, dict) else None,
        "operating_profile": operating_profile,
        "severe_profile": severe_profile,
        "operating_min_return_pct": _profile_stat(profiles, operating_profile, "total_return_pct", "min"),
        "operating_mean_return_pct": _profile_stat(profiles, operating_profile, "total_return_pct", "mean"),
        "operating_min_sharpe": _profile_stat(profiles, operating_profile, "sharpe_ratio", "min"),
        "operating_worst_drawdown_pct": _profile_stat(profiles, operating_profile, "max_drawdown_pct", "min"),
        "severe_min_return_pct": _profile_stat(profiles, severe_profile, "total_return_pct", "min"),
        "severe_mean_return_pct": _profile_stat(profiles, severe_profile, "total_return_pct", "mean"),
        "severe_min_sharpe": _profile_stat(profiles, severe_profile, "sharpe_ratio", "min"),
        "severe_worst_drawdown_pct": _profile_stat(profiles, severe_profile, "max_drawdown_pct", "min"),
    }
    return {key: value for key, value in metrics.items() if value is not None and value != ""}


def _public_promotion_gate_uncertainty(report: dict[str, Any]) -> dict[str, Any]:
    diagnostics = report.get("validation_diagnostics", {}) if isinstance(report, dict) else {}
    aggregate = report.get("aggregate", {}) if isinstance(report, dict) else {}
    return {
        "bootstrap_interval_available": False,
        "pbo_available": False,
        "dsr_available": False,
        "probability_of_improvement_available": False,
        "promotion_gate_status": report.get("status", "missing") if isinstance(report, dict) else "missing",
        "promotion_gate_llm_evidence_status": report.get("llm_evidence_status", "missing")
        if isinstance(report, dict)
        else "missing",
        "blocking_failures": report.get("blocking_failures", []) if isinstance(report, dict) else [],
        "seed_count": aggregate.get("seed_count") if isinstance(aggregate, dict) else None,
        "validation_diagnostics": diagnostics if isinstance(diagnostics, dict) else {},
        "caveat": "Aggregate historical promotion diagnostics do not make RL agent-trustworthy without causal, statistical, calibration, and prospective-shadow gates.",
    }


def _profile_stat(profiles: dict[str, Any], profile: str, metric: str, statistic: str) -> float | str | None:
    if not isinstance(profiles, dict):
        return None
    profile_data = profiles.get(profile, {})
    if not isinstance(profile_data, dict):
        return None
    metric_data = profile_data.get(metric, {})
    if not isinstance(metric_data, dict):
        return None
    return _parse_scalar(metric_data.get(statistic))


def _parse_scalar(value: Any) -> float | str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    try:
        return float(text)
    except ValueError:
        return text


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_status(value: Any) -> str:
    status = str(value or "ABSTAIN").strip().upper()
    return status if status in RL_EVIDENCE_STATES else "ABSTAIN"


def _age_failure_reason(value: Any, *, now: datetime, max_age_secs: int) -> str:
    if not value:
        return "evidence_timestamp_missing"
    try:
        as_of = _parse_utc(str(value))
    except Exception:
        return "evidence_timestamp_invalid"
    if max_age_secs > 0 and (now - as_of).total_seconds() > max_age_secs:
        return "evidence_stale"
    return ""


def _promotion_expiry_failure_reason(envelope: dict[str, Any], *, now: datetime) -> str:
    provenance = envelope.get("provenance", {})
    if not isinstance(provenance, dict):
        return "promotion_metadata_missing"
    expires = str(provenance.get("promotion_expires_utc", "") or "").strip()
    if not expires:
        return "promotion_expiry_missing"
    try:
        if _parse_utc(expires) <= now:
            return "promotion_status_expired"
    except Exception:
        return "promotion_expiry_invalid"
    return ""


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _sanitize_payload(value: Any) -> Any:
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, child in value.items():
            normalized = str(key).strip().lower()
            if normalized in EXECUTABLE_EVIDENCE_KEYS:
                continue
            clean[str(key)] = _sanitize_payload(child)
        return clean
    if isinstance(value, list):
        return [_sanitize_payload(item) for item in value]
    return value
