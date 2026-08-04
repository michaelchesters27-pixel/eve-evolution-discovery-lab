from __future__ import annotations

from typing import Any


def number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


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
        if int(number(counts.get(str(key)), minimum_trades)) >= minimum_trades
    ]
    if not parsed:
        return None, None
    parsed.sort(key=lambda item: item[1])
    return parsed[-1][0], parsed[0][0]


def _schedule_text(schedule: dict[str, Any]) -> str:
    sessions = [str(value).replace("_", " ") for value in schedule.get("sessions") or []]
    hours = [int(value) for value in schedule.get("hours_utc") or []]
    if sessions:
        return ", ".join(sessions)
    if len(hours) == 24:
        return "All configured market hours"
    if hours:
        if len(hours) == 1:
            return f"{hours[0]:02d}:00–{(hours[0] + 1) % 24:02d}:00 UTC"
        return f"UTC hours {', '.join(f'{value:02d}' for value in hours)}"
    return "No fixed session restriction"


def _condition_summary(rules: dict[str, Any]) -> list[str]:
    environment = dict(rules.get("environment") or {})
    result: list[str] = []
    if environment.get("regimes"):
        result.append("Regimes: " + ", ".join(str(value).replace("_", " ") for value in environment["regimes"]))
    for key, label in (("trend_12", "short trend"), ("trend_48", "long trend"), ("compression", "volatility")):
        value = str(environment.get(key) or "any")
        if value != "any":
            result.append(f"{label}: {value.replace('_', ' ')}")
    minimum = int(number(environment.get("min_alignment_abs")))
    if minimum:
        result.append(f"alignment strength at least {minimum}")
    if not result:
        result.append("No additional regime restriction")
    return result


def build_trading_passport(frozen: dict[str, Any]) -> dict[str, Any]:
    rules = dict(frozen.get("rules") or {})
    market = dict(rules.get("market") or {})
    schedule = dict(rules.get("schedule") or {})
    risk = dict(rules.get("risk") or {})
    metrics = dict(frozen.get("metrics") or {})
    confirmation = dict(metrics.get("confirmation") or metrics.get("locked") or {})
    holdout = dict(metrics.get("holdout") or metrics.get("recent") or {})
    validation = dict(metrics.get("validation") or {})
    session_metrics = holdout if holdout.get("session_expectancy") else confirmation if confirmation.get("session_expectancy") else validation
    regime_metrics = holdout if holdout.get("regime_expectancy") else confirmation if confirmation.get("regime_expectancy") else validation
    session_source = session_metrics.get("session_expectancy") or {}
    regime_source = regime_metrics.get("regime_expectancy") or {}
    session_counts = session_metrics.get("session_trades") or {}
    regime_counts = regime_metrics.get("regime_trades") or {}
    best_session, worst_session = _best_worst(session_source, session_counts)
    best_regime, worst_regime = _best_worst(regime_source, regime_counts)
    timeframe = str(market.get("timeframe") or frozen.get("timeframe") or "M5").upper()
    symbol = str(market.get("symbol") or frozen.get("symbol") or "XAU/USD")
    family = str(frozen.get("family") or rules.get("family") or "strategy").replace("_", " ")
    status = str(frozen.get("result_status") or frozen.get("status") or "validated")
    stability = number(frozen.get("stability_score"))
    robust = number((frozen.get("robustness") or {}).get("pass_rate")) * 100.0
    holdout_pf = number(holdout.get("profit_factor"))
    confidence = max(0.0, min(100.0, stability * 0.35 + robust * 0.30 + min(30.0, max(0.0, (holdout_pf - 1.0) * 50.0)) + (5.0 if status == "elite" else 0.0)))

    use_when = [
        f"Attach to a {symbol} {timeframe} chart.",
        f"Operate during {_schedule_text(schedule)}.",
        *_condition_summary(rules),
    ]
    if best_session:
        use_when.append(
            f"Strongest observed session: {best_session.replace('_', ' ')} "
            f"({int(number(session_counts.get(best_session)))} final-stage trades)."
        )
    if best_regime:
        use_when.append(
            f"Strongest observed regime: {best_regime.replace('_', ' ')} "
            f"({int(number(regime_counts.get(best_regime)))} final-stage trades)."
        )

    avoid_when = [
        f"Spread exceeds {int(number(risk.get('max_spread_points'), 100))} broker points.",
        "The chart timeframe or symbol does not match this passport.",
        "The EA is not on a demo account during forward validation.",
    ]
    if worst_session and worst_session != best_session:
        avoid_when.append(
            f"Weakest observed session: {worst_session.replace('_', ' ')} "
            f"({int(number(session_counts.get(worst_session)))} final-stage trades)."
        )
    if worst_regime and worst_regime != best_regime:
        avoid_when.append(
            f"Weakest observed regime: {worst_regime.replace('_', ' ')} "
            f"({int(number(regime_counts.get(worst_regime)))} final-stage trades)."
        )

    weekday_names = {1: "Monday", 2: "Tuesday", 3: "Wednesday", 4: "Thursday", 5: "Friday", 6: "Saturday", 7: "Sunday"}
    weekdays = [weekday_names.get(int(value), str(value)) for value in schedule.get("weekdays") or []]
    return {
        "passport_version": "eve-trading-passport-v1",
        "strategy_name": frozen.get("name"),
        "strategy_code": frozen.get("strategy_code"),
        "rule_hash": frozen.get("rule_hash"),
        "purpose": f"{family.title()} strategy designed from EVE's historical market-state research.",
        "market": symbol,
        "primary_timeframe": timeframe,
        "attach_to_chart": f"{symbol} {timeframe}",
        "attach_chart": f"{symbol} {timeframe}",
        "research_snapshot_interval": market.get("snapshot_interval") or "15min",
        "research_source_interval": market.get("source_interval") or "5min",
        "operating_window": _schedule_text(schedule),
        "weekdays": weekdays,
        "months": schedule.get("months") or [],
        "best_session": best_session,
        "best_session_trades": int(number(session_counts.get(best_session))) if best_session else 0,
        "weakest_session": worst_session,
        "weakest_session_trades": int(number(session_counts.get(worst_session))) if worst_session else 0,
        "best_regime": best_regime,
        "best_regime_trades": int(number(regime_counts.get(best_regime))) if best_regime else 0,
        "weakest_regime": worst_regime,
        "weakest_regime_trades": int(number(regime_counts.get(worst_regime))) if worst_regime else 0,
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
        },
        "evidence": {
            "validation_profit_factor": number(validation.get("profit_factor")),
            "confirmation_profit_factor": number(confirmation.get("profit_factor")),
            "holdout_profit_factor": number(holdout.get("profit_factor")),
            "holdout_expectancy_r": number(holdout.get("expectancy_r")),
            "stability_score": stability,
            "robustness_percent": robust,
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


def passport_text(passport: dict[str, Any]) -> str:
    lines = [
        "EVE TRADING PASSPORT",
        "",
        f"Strategy: {passport.get('strategy_name')}",
        f"Code: {passport.get('strategy_code')}",
        f"Market: {passport.get('market')}",
        f"Primary timeframe: {passport.get('primary_timeframe')}",
        f"Attach to: {passport.get('attach_to_chart')}",
        f"Operating window: {passport.get('operating_window')}",
        f"Research source interval: {passport.get('research_source_interval')}",
        f"Confidence: {passport.get('confidence_score')}/100",
        f"Status: {passport.get('deployment_status')}",
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
        "IMPORTANT",
        "- This passport describes the conditions in which the strategy was researched.",
        "- It is not a guarantee of future profitability.",
        "- Compile in MetaEditor and run demo forward testing before any other use.",
    ]
    return "\n".join(lines) + "\n"
