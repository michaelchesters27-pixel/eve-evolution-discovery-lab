from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.services import live_trader as core

COST_MODEL_VERSION = "eve-live-execution-cost-model-v1"
PROFILE_NAME = "xauusd-manual-stress-v1"


def _num(value: Any, default: float = 0.0) -> float:
    return core.number(value, default)


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def first_full_m1_at_or_after(value: datetime) -> datetime:
    value = value.astimezone(timezone.utc)
    minute = value.replace(second=0, microsecond=0)
    return minute if value == minute else minute + timedelta(minutes=1)


def profile_from_settings(settings: Any) -> dict[str, Any]:
    return {
        "version": COST_MODEL_VERSION,
        "profile": PROFILE_NAME,
        "source": "predeclared_xauusd_manual_execution_stress_assumptions",
        "spread_price": round(max(0.0, _num(getattr(settings, "live_trader_cost_spread_price", 0.30), 0.30)), 5),
        "entry_slippage_price": round(max(0.0, _num(getattr(settings, "live_trader_cost_entry_slippage_price", 0.10), 0.10)), 5),
        "exit_slippage_price": round(max(0.0, _num(getattr(settings, "live_trader_cost_exit_slippage_price", 0.10), 0.10)), 5),
        "commission_price_equivalent": round(
            max(0.0, _num(getattr(settings, "live_trader_cost_commission_price_equivalent", 0.07), 0.07)), 5
        ),
        "manual_delay_seconds": int(max(0, _num(getattr(settings, "live_trader_manual_delay_seconds", 15), 15))),
        "actual_bid_ask_quotes": False,
        "actual_broker_fill": False,
        "purpose": (
            "Convert explicit raw-price execution assumptions into R using each trade's original planned risk distance. "
            "This is a conservative stress estimate, not a claim about an actual broker fill."
        ),
    }


def profile_from_trade(trade: dict[str, Any]) -> dict[str, Any]:
    raw = trade.get("execution_cost_model")
    if isinstance(raw, dict) and str(raw.get("version") or "") == COST_MODEL_VERSION:
        return dict(raw)
    # Historical rows created before v90 use the production defaults during the
    # versioned regrade. They are explicitly marked as a reconstructed stress profile.
    return {
        "version": COST_MODEL_VERSION,
        "profile": PROFILE_NAME,
        "source": "historical_regrade_default_stress_assumptions",
        "spread_price": 0.30,
        "entry_slippage_price": 0.10,
        "exit_slippage_price": 0.10,
        "commission_price_equivalent": 0.07,
        "manual_delay_seconds": 15,
        "actual_bid_ask_quotes": False,
        "actual_broker_fill": False,
        "purpose": "Historical stress-cost reconstruction; not an actual broker fill.",
    }


def manual_execution_start(activation: datetime, profile: dict[str, Any]) -> tuple[datetime, datetime]:
    delay = timedelta(seconds=max(0, int(_num(profile.get("manual_delay_seconds"), 0))))
    eligible = activation + delay
    return eligible, first_full_m1_at_or_after(eligible)


def _manual_delay_adverse_price(
    trade: dict[str, Any],
    bars: list[dict[str, Any]],
) -> tuple[float, float | None]:
    if str(trade.get("order_type") or "").lower() != "market" or not bars:
        return 0.0, None
    first_open = _num((bars[0] or {}).get("open"))
    entry = _num(trade.get("entry"))
    side = str(trade.get("side") or "").upper()
    if first_open <= 0 or entry <= 0 or side not in {"BUY", "SELL"}:
        return 0.0, first_open if first_open > 0 else None
    adverse = max(0.0, first_open - entry) if side == "BUY" else max(0.0, entry - first_open)
    return adverse, first_open


def apply_cost_model(
    trade: dict[str, Any],
    gross_result: dict[str, Any],
    bars: list[dict[str, Any]],
) -> dict[str, Any]:
    result = dict(gross_result)
    gross_r = result.get("realised_r")
    triggered = result.get("entry_triggered")
    profile = profile_from_trade(trade)

    result["gross_realised_r"] = gross_r
    result["cost_model_version"] = COST_MODEL_VERSION

    if triggered is not True or gross_r is None:
        result["estimated_cost_r"] = 0.0 if triggered is False and gross_r is not None else None
        result["net_realised_r"] = gross_r
        result["net_learning_success"] = None
        result["execution_costs"] = {
            "version": COST_MODEL_VERSION,
            "profile": profile.get("profile"),
            "triggered": triggered,
            "cost_applied": False,
            "reason": "No execution cost charged because capital was not exposed." if triggered is False else "No scorable realised R.",
        }
        return result

    entry = _num(trade.get("entry"))
    stop = _num(trade.get("stop"))
    planned_risk_price = abs(entry - stop)
    if planned_risk_price <= 0:
        result["estimated_cost_r"] = None
        result["net_realised_r"] = None
        result["net_learning_success"] = None
        result["execution_costs"] = {
            "version": COST_MODEL_VERSION,
            "profile": profile.get("profile"),
            "cost_applied": False,
            "reason": "Invalid planned risk distance.",
        }
        return result

    manual_adverse, manual_reference = _manual_delay_adverse_price(trade, bars)
    spread = max(0.0, _num(profile.get("spread_price")))
    entry_slip = max(0.0, _num(profile.get("entry_slippage_price")))
    exit_slip = max(0.0, _num(profile.get("exit_slippage_price")))
    commission = max(0.0, _num(profile.get("commission_price_equivalent")))
    total_cost_price = spread + entry_slip + exit_slip + commission + manual_adverse
    cost_r = total_cost_price / planned_risk_price
    net_r = _num(gross_r) - cost_r

    gross_success = result.get("learning_success")
    if net_r >= 0.15:
        net_success: bool | None = True
    elif net_r <= -0.15:
        net_success = False
    else:
        net_success = None

    result["estimated_cost_r"] = round(cost_r, 5)
    result["net_realised_r"] = round(net_r, 5)
    result["net_learning_success"] = net_success
    # Future learning must reflect the cost-adjusted result. Preserve the gross
    # classification in the breakdown so the measurement change remains auditable.
    result["learning_success"] = net_success
    result["execution_costs"] = {
        "version": COST_MODEL_VERSION,
        "profile": profile.get("profile"),
        "source": profile.get("source"),
        "planned_risk_price": round(planned_risk_price, 5),
        "spread_price": round(spread, 5),
        "entry_slippage_price": round(entry_slip, 5),
        "exit_slippage_price": round(exit_slip, 5),
        "commission_price_equivalent": round(commission, 5),
        "manual_delay_seconds": int(_num(profile.get("manual_delay_seconds"))),
        "manual_delay_reference_price": round(manual_reference, 5) if manual_reference is not None else None,
        "manual_delay_adverse_price": round(manual_adverse, 5),
        "total_cost_price": round(total_cost_price, 5),
        "estimated_cost_r": round(cost_r, 5),
        "gross_realised_r": round(_num(gross_r), 5),
        "net_realised_r": round(net_r, 5),
        "gross_learning_success": gross_success,
        "net_learning_success": net_success,
        "actual_bid_ask_quotes": bool(profile.get("actual_bid_ask_quotes")),
        "actual_broker_fill": bool(profile.get("actual_broker_fill")),
        "not_actual_fill_warning": (
            "Stress-estimated execution cost only. Actual MT5 fill, bid/ask, commission and latency must be recorded separately."
        ),
    }
    return result


def campaign_cost_result(campaign: dict[str, Any], gross_r: float) -> dict[str, Any]:
    trade = {
        "side": campaign.get("side"),
        "order_type": campaign.get("order_type"),
        "entry": campaign.get("entry"),
        "stop": campaign.get("stop"),
        "target": campaign.get("target"),
        "execution_cost_model": campaign.get("execution_cost_model") or {},
    }
    activation_price = _num(campaign.get("activation_price"))
    bars = [{"open": activation_price}] if activation_price > 0 else []
    return apply_cost_model(
        trade,
        {
            "entry_triggered": bool(campaign.get("triggered_at")),
            "trade_outcome": campaign.get("status"),
            "realised_r": gross_r,
            "learning_success": True if gross_r > 0 else False if gross_r < 0 else None,
        },
        bars,
    )
