from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

PROFILE_VERSION = "eve-strategy-profile-v2"
PASSPORT_VERSION = "eve-trading-passport-v2"

_PLACEHOLDERS = {
    "",
    "—",
    "-",
    "none",
    "null",
    "not specified",
    "not established",
    "unknown",
    "dataset not assigned",
}


def number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() not in _PLACEHOLDERS
    return True


def _human_key(value: Any) -> str:
    return str(value or "").replace("_", " ").strip().title()


def _best_worst(
    values: dict[str, Any],
    counts: dict[str, Any] | None = None,
    *,
    minimum_trades: int = 10,
) -> tuple[str | None, str | None]:
    counts = counts or {}
    parsed = [
        (str(key), number(value))
        for key, value in (values or {}).items()
        if int(number(counts.get(str(key)), 0)) >= minimum_trades
    ]
    if not parsed:
        return None, None
    parsed.sort(key=lambda item: item[1])
    return parsed[-1][0], parsed[0][0]


def _schedule_text(schedule: dict[str, Any]) -> str:
    sessions = [_human_key(value) for value in schedule.get("sessions") or []]
    hours = sorted({int(value) for value in schedule.get("hours_utc") or []})
    if sessions:
        return ", ".join(sessions)
    if len(hours) == 24:
        return "All configured market hours"
    if hours:
        contiguous = all(hours[index] + 1 == hours[index + 1] for index in range(len(hours) - 1))
        if contiguous:
            return f"{hours[0]:02d}:00–{(hours[-1] + 1) % 24:02d}:00 UTC"
        return "UTC hours " + ", ".join(f"{value:02d}:00" for value in hours)
    return "No fixed session restriction; the entry rules decide when to trade"


def _condition_summary(rules: dict[str, Any]) -> list[str]:
    environment = dict(rules.get("environment") or {})
    result: list[str] = []
    if environment.get("regimes"):
        result.append("Preferred regimes: " + ", ".join(_human_key(value) for value in environment["regimes"]))
    for key, label in (("trend_12", "short trend"), ("trend_48", "long trend"), ("compression", "volatility")):
        value = str(environment.get(key) or "any")
        if value != "any":
            result.append(f"Required {label}: {_human_key(value)}")
    minimum = int(number(environment.get("min_alignment_abs")))
    if minimum:
        result.append(f"Market alignment strength must be at least {minimum}")
    if not result:
        result.append("No extra market-regime restriction beyond the frozen entry rules")
    return result


def _metric_source(metrics: dict[str, Any]) -> tuple[dict[str, Any], str]:
    for key, label in (
        ("holdout", "final holdout"),
        ("recent", "legacy final period"),
        ("confirmation", "confirmation"),
        ("locked", "legacy confirmation"),
        ("validation", "validation"),
    ):
        source = dict(metrics.get(key) or {})
        if not source.get("sealed") and number(source.get("trades")) > 0:
            return source, label
    return {}, "no completed profile segment"


def _weekday_label(key: str | None) -> str | None:
    if key is None:
        return None
    names = {"1": "Monday", "2": "Tuesday", "3": "Wednesday", "4": "Thursday", "5": "Friday", "6": "Saturday", "7": "Sunday"}
    return names.get(str(key), _human_key(key))


def _hour_label(key: str | None) -> str | None:
    if key is None:
        return None
    hour = int(number(key)) % 24
    return f"{hour:02d}:00–{(hour + 1) % 24:02d}:00 UTC"


def passport_completeness(passport: dict[str, Any]) -> dict[str, Any]:
    required_scalars = {
        "market": passport.get("market"),
        "primary_timeframe": passport.get("primary_timeframe"),
        "attach_to_chart": passport.get("attach_to_chart") or passport.get("attach_chart"),
        "operating_window": passport.get("operating_window"),
        "best_session": passport.get("best_session"),
        "best_regime": passport.get("best_regime"),
        "confidence_score": passport.get("confidence_score"),
        "dataset_version": (passport.get("evidence") or {}).get("dataset_version"),
        "deployment_status": passport.get("deployment_status"),
    }
    missing = [name for name, value in required_scalars.items() if not _present(value)]
    if not passport.get("use_when"):
        missing.append("use_when")
    if not passport.get("avoid_when"):
        missing.append("avoid_when")
    risk = dict(passport.get("risk") or {})
    for field in ("stop_atr", "target_atr", "maximum_hold_minutes", "maximum_spread_points"):
        if field not in risk or risk.get(field) is None:
            missing.append(f"risk.{field}")
    checks = {
        "market_and_timeframe": not any(item in missing for item in ("market", "primary_timeframe", "attach_to_chart")),
        "operating_conditions": not any(item in missing for item in ("operating_window", "best_session", "best_regime", "use_when", "avoid_when")),
        "risk_profile": not any(item.startswith("risk.") for item in missing),
        "evidence_trace": "dataset_version" not in missing,
        "operator_guidance": bool(passport.get("use_when")) and bool(passport.get("avoid_when")),
    }
    return {"complete": not missing, "missing_fields": missing, "checks": checks}


def passport_is_complete(passport: dict[str, Any] | None) -> bool:
    return bool(passport and passport_completeness(dict(passport)).get("complete"))


def build_trading_passport(
    frozen: dict[str, Any],
    *,
    profile_origin: str = "automatic_finalist_profile",
) -> dict[str, Any]:
    rules = dict(frozen.get("rules") or {})
    market = dict(rules.get("market") or {})
    schedule = dict(rules.get("schedule") or {})
    risk = dict(rules.get("risk") or {})
    metrics = dict(frozen.get("metrics") or {})
    profile_metrics, profile_segment = _metric_source(metrics)
    validation = dict(metrics.get("validation") or {})
    confirmation = dict(metrics.get("confirmation") or metrics.get("locked") or {})
    holdout = dict(metrics.get("holdout") or metrics.get("recent") or {})

    total_profile_trades = int(number(profile_metrics.get("trades")))
    minimum_bucket_trades = max(5, min(20, int(total_profile_trades * 0.05))) if total_profile_trades else 10

    best_session_key, worst_session_key = _best_worst(
        profile_metrics.get("session_expectancy") or {},
        profile_metrics.get("session_trades") or {},
        minimum_trades=minimum_bucket_trades,
    )
    best_regime_key, worst_regime_key = _best_worst(
        profile_metrics.get("regime_expectancy") or {},
        profile_metrics.get("regime_trades") or {},
        minimum_trades=minimum_bucket_trades,
    )
    best_weekday_key, worst_weekday_key = _best_worst(
        profile_metrics.get("weekday_expectancy") or {},
        profile_metrics.get("weekday_trades") or {},
        minimum_trades=minimum_bucket_trades,
    )
    best_hour_key, worst_hour_key = _best_worst(
        profile_metrics.get("hour_expectancy") or {},
        profile_metrics.get("hour_trades") or {},
        minimum_trades=minimum_bucket_trades,
    )

    timeframe = str(market.get("timeframe") or frozen.get("timeframe") or "M5").upper()
    symbol = str(market.get("symbol") or frozen.get("symbol") or "XAU/USD")
    family = str(frozen.get("family") or rules.get("family") or "strategy").replace("_", " ")
    status = str(frozen.get("result_status") or frozen.get("status") or "validated")
    stability = number(frozen.get("stability_score"))
    robustness = dict(frozen.get("robustness") or {})
    robust = number(robustness.get("pass_rate")) * 100.0
    holdout_pf = number(holdout.get("profit_factor"))
    m1 = dict(frozen.get("m1_replay") or {})
    m1_bonus = 8.0 if m1.get("passed") else 0.0
    confidence = max(
        0.0,
        min(
            100.0,
            stability * 0.32
            + robust * 0.28
            + min(27.0, max(0.0, (holdout_pf - 1.0) * 45.0))
            + m1_bonus
            + (5.0 if status == "elite" else 0.0),
        ),
    )

    best_session = _human_key(best_session_key) if best_session_key else "No reliable session advantage established"
    weakest_session = _human_key(worst_session_key) if worst_session_key else "No reliable weak session established"
    best_regime = _human_key(best_regime_key) if best_regime_key else "No reliable regime advantage established"
    weakest_regime = _human_key(worst_regime_key) if worst_regime_key else "No reliable weak regime established"
    best_weekday = _weekday_label(best_weekday_key) or "No reliable weekday advantage established"
    weakest_weekday = _weekday_label(worst_weekday_key) or "No reliable weak weekday established"
    best_hour = _hour_label(best_hour_key) or "No reliable hourly advantage established"
    weakest_hour = _hour_label(worst_hour_key) or "No reliable weak hour established"

    use_when = [
        f"Attach the EA to a {symbol} {timeframe} chart.",
        f"Use the configured operating window: {_schedule_text(schedule)}.",
        *_condition_summary(rules),
    ]
    if best_session_key:
        use_when.append(
            f"Strongest observed session: {best_session} "
            f"({int(number((profile_metrics.get('session_trades') or {}).get(best_session_key)))} {profile_segment} trades)."
        )
    else:
        use_when.append("No statistically reliable session advantage was found; keep the frozen schedule unchanged.")
    if best_regime_key:
        use_when.append(
            f"Strongest observed market regime: {best_regime} "
            f"({int(number((profile_metrics.get('regime_trades') or {}).get(best_regime_key)))} {profile_segment} trades)."
        )
    else:
        use_when.append("No statistically reliable regime advantage was found beyond the frozen entry filters.")

    avoid_when = [
        f"Do not use when the spread exceeds {int(number(risk.get('max_spread_points'), 100))} broker points.",
        f"Do not attach it to a symbol or timeframe other than {symbol} {timeframe}.",
        "Do not treat the package as live-trading approval; MetaEditor compilation and demo forward testing are mandatory.",
    ]
    if worst_session_key and worst_session_key != best_session_key:
        avoid_when.append(
            f"Weakest observed session: {weakest_session} "
            f"({int(number((profile_metrics.get('session_trades') or {}).get(worst_session_key)))} {profile_segment} trades)."
        )
    else:
        avoid_when.append("No separate weak session met the minimum sample requirement.")
    if worst_regime_key and worst_regime_key != best_regime_key:
        avoid_when.append(
            f"Weakest observed regime: {weakest_regime} "
            f"({int(number((profile_metrics.get('regime_trades') or {}).get(worst_regime_key)))} {profile_segment} trades)."
        )
    else:
        avoid_when.append("No separate weak regime met the minimum sample requirement.")

    weekday_names = {1: "Monday", 2: "Tuesday", 3: "Wednesday", 4: "Thursday", 5: "Friday", 6: "Saturday", 7: "Sunday"}
    weekdays = [weekday_names.get(int(value), str(value)) for value in schedule.get("weekdays") or []]
    passport: dict[str, Any] = {
        "passport_version": PASSPORT_VERSION,
        "profile_version": PROFILE_VERSION,
        "profile_status": "complete",
        "profile_origin": profile_origin,
        "profiled_at": datetime.now(timezone.utc).isoformat(),
        "profile_segment": profile_segment,
        "minimum_bucket_trades": minimum_bucket_trades,
        "strategy_name": frozen.get("name"),
        "strategy_code": frozen.get("strategy_code"),
        "rule_hash": frozen.get("rule_hash"),
        "purpose": f"{family.title()} strategy produced from EVE's historical market-state research.",
        "market": symbol,
        "primary_timeframe": timeframe,
        "attach_to_chart": f"{symbol} {timeframe}",
        "attach_chart": f"{symbol} {timeframe}",
        "research_snapshot_interval": market.get("snapshot_interval") or frozen.get("snapshot_interval") or "15min",
        "research_source_interval": market.get("source_interval") or frozen.get("source_interval") or "5min",
        "operating_window": _schedule_text(schedule),
        "weekdays": weekdays or ["All configured weekdays"],
        "months": schedule.get("months") or ["All configured months"],
        "best_session_key": best_session_key,
        "best_session": best_session,
        "best_session_trades": int(number((profile_metrics.get("session_trades") or {}).get(best_session_key))) if best_session_key else 0,
        "weakest_session_key": worst_session_key,
        "weakest_session": weakest_session,
        "weakest_session_trades": int(number((profile_metrics.get("session_trades") or {}).get(worst_session_key))) if worst_session_key else 0,
        "best_regime_key": best_regime_key,
        "best_regime": best_regime,
        "best_regime_trades": int(number((profile_metrics.get("regime_trades") or {}).get(best_regime_key))) if best_regime_key else 0,
        "weakest_regime_key": worst_regime_key,
        "weakest_regime": weakest_regime,
        "weakest_regime_trades": int(number((profile_metrics.get("regime_trades") or {}).get(worst_regime_key))) if worst_regime_key else 0,
        "best_weekday_key": best_weekday_key,
        "best_weekday": best_weekday,
        "weakest_weekday_key": worst_weekday_key,
        "weakest_weekday": weakest_weekday,
        "best_hour_utc_key": best_hour_key,
        "best_hour_utc": best_hour,
        "weakest_hour_utc_key": worst_hour_key,
        "weakest_hour_utc": weakest_hour,
        "use_when": use_when,
        "avoid_when": avoid_when,
        "risk": {
            "stop_atr": number(risk.get("stop_atr"), 1.0),
            "target_atr": number(risk.get("target_atr"), 2.0),
            "maximum_hold_minutes": int(number(risk.get("max_hold_minutes"), risk.get("horizon_minutes") or 60)),
            "cooldown_minutes": int(number(risk.get("cooldown_minutes"), 60)),
            "maximum_spread_points": int(number(risk.get("max_spread_points"), 100)),
            "risk_percent_default": number(risk.get("risk_percent"), 0.25),
        },
        "expected_activity": {
            "validation_trades_per_day": number(validation.get("trades_per_day")),
            "confirmation_trades_per_day": number(confirmation.get("trades_per_day")),
            "holdout_trades_per_day": number(holdout.get("trades_per_day")),
            "profile_trades": total_profile_trades,
        },
        "evidence": {
            "profile_segment": profile_segment,
            "validation_profit_factor": number(validation.get("profit_factor")),
            "confirmation_profit_factor": number(confirmation.get("profit_factor")),
            "holdout_profit_factor": number(holdout.get("profit_factor")),
            "holdout_expectancy_r": number(holdout.get("expectancy_r")),
            "stability_score": stability,
            "robustness_percent": robust,
            "m1_replay_status": m1.get("status") or "not recorded",
            "dataset_version": frozen.get("dataset_version") or (frozen.get("evidence") or {}).get("dataset", {}).get("version"),
        },
        "confidence_score": round(confidence, 1),
        "deployment_status": "Demo forward testing only",
        "compile_status": "MetaEditor compilation required",
        "telemetry": {
            "algo_lab_compatible": True,
            "configuration_required": True,
            "note": "Set the Algo Lab fleet endpoint and token in EA Inputs after import into Project 1.",
        },
    }
    passport["completeness"] = passport_completeness(passport)
    passport["profile_status"] = "complete" if passport["completeness"]["complete"] else "failed"
    return passport


def passport_text(passport: dict[str, Any]) -> str:
    completeness = dict(passport.get("completeness") or passport_completeness(passport))
    lines = [
        "EVE TRADING PASSPORT",
        "",
        f"Profile status: {passport.get('profile_status')}",
        f"Profile version: {passport.get('profile_version')}",
        f"Strategy: {passport.get('strategy_name')}",
        f"Code: {passport.get('strategy_code')}",
        f"Market: {passport.get('market')}",
        f"Primary timeframe: {passport.get('primary_timeframe')}",
        f"Attach to: {passport.get('attach_to_chart')}",
        f"Operating window: {passport.get('operating_window')}",
        f"Best session: {passport.get('best_session')}",
        f"Best market regime: {passport.get('best_regime')}",
        f"Best weekday: {passport.get('best_weekday')}",
        f"Best UTC hour: {passport.get('best_hour_utc')}",
        f"Research source interval: {passport.get('research_source_interval')}",
        f"Confidence: {passport.get('confidence_score')}/100",
        f"Status: {passport.get('deployment_status')}",
        f"Dataset: {(passport.get('evidence') or {}).get('dataset_version')}",
        "",
        "USE WHEN",
        *[f"- {item}" for item in passport.get("use_when") or []],
        "",
        "AVOID WHEN",
        *[f"- {item}" for item in passport.get("avoid_when") or []],
        "",
        "RISK PROFILE",
        *[f"- {key.replace('_', ' ').title()}: {value}" for key, value in (passport.get("risk") or {}).items()],
        "",
        "PROFILE COMPLETENESS",
        f"- Complete: {'YES' if completeness.get('complete') else 'NO'}",
        f"- Missing fields: {', '.join(completeness.get('missing_fields') or []) or 'None'}",
        "",
        "IMPORTANT",
        "- This passport describes the conditions in which the strategy was researched.",
        "- It is not a guarantee of future profitability.",
        "- Compile in MetaEditor and run demo forward testing before any other use.",
    ]
    return "\n".join(lines)
