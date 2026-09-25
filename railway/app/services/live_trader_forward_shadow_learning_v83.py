from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services import live_trader as core
from app.services import live_trader_context_contract as context_contract
from app.services import live_trader_audit_hardening_v26 as hardening
from app.services import live_trader_execution_cost_model as cost_model
from app.services import live_trader_evidence_identity as evidence_id
from app.services import live_trader_evidence_quality_v92 as quality
from app.services import live_trader_learning_v2 as v2
from app.services import live_trader_learning_v22 as v22
from app.services import live_trader_london_session_gate_v46 as session_gate

VERSION = "eve-live-forward-shadow-learning-v83"
SHADOW_VERSION = "eve-live-shadow-trades-v1"
SHADOW_TARGET_R = 1.5
SHADOW_MIN_ZONE_QUALITY = 55.0
SHADOW_MAX_ZONE_DISTANCE_ATR = 2.75
MAX_OBSERVATION_AGE_SECONDS = 120.0
SHADOW_RESOLVE_LIMIT = 8
SHADOW_RESOLVE_INTERVAL_SECONDS = 45.0
TRADE_SKILL_CACHE_SECONDS = 60.0

_current_refresh_state = core.LiveTrader.refresh_state
_current_learning_summary = core.LiveTrader.learning_summary
_current_runtime_status = core.LiveTrader.runtime_status


def _shadow_policy_definition(variant: str) -> dict[str, Any]:
    variant_rules = {
        "market_probe": "Immediate market probe using nearest matching quality zone for stop geometry.",
        "zone_touch_limit": "First-touch limit at nearest matching quality zone boundary.",
        "momentum_confirmation": "0.15 ATR directional stop-entry confirmation with 0.85 ATR opposing stop geometry.",
    }
    return {
        "contract_version": "eve-live-shadow-policy-contract-v1",
        "forward_shadow_version": VERSION,
        "learning_version": SHADOW_VERSION,
        "variant": variant,
        "variant_rule": variant_rules.get(variant, "unknown"),
        "target_r": SHADOW_TARGET_R,
        "minimum_zone_quality": SHADOW_MIN_ZONE_QUALITY,
        "live_zone_distance_gate_applied": False,
        "publication_authority": False,
        "manual_only": True,
        "automatic_order_placement": False,
        "live_context_contract": context_contract.definition(),
    }


def _shadow_identity(self: core.LiveTrader, variant: str) -> dict[str, Any]:
    return evidence_id.build_identity(
        policy_kind="forward_shadow_research",
        policy_key=variant,
        policy_definition=_shadow_policy_definition(variant),
        settings=self.settings,
        learning_version=SHADOW_VERSION,
        evaluation_stage="shadow_forward_research",
    )


def _production_forward_identity(self: core.LiveTrader) -> dict[str, Any]:
    return evidence_id.production_identity(
        self.settings,
        learning_version=hardening.LEARNING_NAMESPACE,
        evaluation_stage="production_forward_learning",
    )


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


def _recent_observation_time(state: dict[str, Any], *, now: datetime | None = None) -> datetime | None:
    """Return the freshest decision timestamp that is safe to learn from.

    v2.6 originally preferred state.as_of. The live state has since gained several
    wrappers, so use the explicit feed timestamp first and only fall back to
    state.as_of. This makes forward learning self-healing if a display wrapper
    changes as_of semantics without changing the market observation itself.
    """
    current = now or core.utc_now()
    feed = dict(state.get("feed") or {})
    if not bool(feed.get("connected")):
        return None
    observed = _parse_time(feed.get("last_tick_at")) or _parse_time(state.get("as_of"))
    if observed is None or observed > current + timedelta(seconds=5):
        return None
    age = (current - observed).total_seconds()
    if age < 0 or age > MAX_OBSERVATION_AGE_SECONDS:
        return None
    return observed


def _forward_episode_key(state: dict[str, Any]) -> str:
    return v22.episode_key(state)


async def _ensure_forward_observation(self: core.LiveTrader, state: dict[str, Any]) -> dict[str, Any]:
    diagnostics = {
        "version": VERSION,
        "status": "skipped",
        "learning_version": hardening.LEARNING_NAMESPACE,
        "timing_contract_version": hardening.TIMING_CONTRACT_VERSION,
    }
    observed = _recent_observation_time(state)
    if observed is None:
        diagnostics["reason"] = "no_recent_connected_observation"
        return diagnostics

    family = str(state.get("setup_family") or state.get("setup_signature") or "")
    if not family:
        diagnostics["reason"] = "no_setup_family"
        return diagnostics
    episode = _forward_episode_key(state)
    identity = _production_forward_identity(self)

    try:
        await evidence_id.ensure_registered(self.repo, identity)
        existing = await self.repo.client.get(
            "live_trader_opinions",
            params={
                "select": "id,observed_at,status,timing_contract_version,activation_at",
                "learning_version": f"eq.{hardening.LEARNING_NAMESPACE}",
                "cohort_id": f"eq.{identity['cohort_id']}",
                "setup_family": f"eq.{family}",
                "episode_key": f"eq.{episode}",
                "limit": "1",
            },
        )
        if existing:
            diagnostics.update({
                "status": "present",
                "episode_key": episode,
                "setup_family": family,
                "timing_contract_version": (existing[0] or {}).get("timing_contract_version"),
                "activation_at": (existing[0] or {}).get("activation_at"),
                "evidence_identity": evidence_id.public_identity(identity),
            })
            return diagnostics

        decision_at = core.utc_now()
        market_state = {
            "market": state.get("market"),
            "bias": state.get("bias"),
            "liquidity": state.get("liquidity"),
            "setup_family_descriptor": state.get("setup_family_descriptor"),
            "learning_observation": {
                "policy": hardening.OBSERVATION_POLICY,
                "market_observed_at": observed.isoformat(),
                "engine_version": hardening.ENGINE_VERSION,
                "outcome_schema": hardening.OUTCOME_SCHEMA,
                "forward_recorder": VERSION,
                "self_healing_fallback": True,
            },
            "evidence_identity": evidence_id.public_identity(identity),
        }
        row, timing = await hardening._insert_timed_forward_opinion(
            self,
            {
                "observed_at": observed.isoformat(),
                "symbol": self.symbol,
                "price": state.get("price"),
                "bias": (state.get("bias") or {}).get("overall"),
                "confidence": (state.get("bias") or {}).get("confidence"),
                "horizon_minutes": self.settings.live_trader_learning_horizon_minutes,
                "setup_signature": family,
                "setup_family": family,
                "episode_key": episode,
                "learning_version": hardening.LEARNING_NAMESPACE,
                "independent_sample": True,
                "zones": state.get("zones") or {},
                "trade_idea": evidence_id.attach_trade(dict(state.get("trade") or {}), identity),
                "opinion_text": state.get("opinion") or "",
                "status": "open",
                **evidence_id.row_columns(identity),
            },
            observed=observed,
            market_state=market_state,
            decision_at=decision_at,
        )
        if row is None or not timing.get("activation_at"):
            diagnostics.update({"status": "error", "reason": "forward_observation_not_durably_activated"})
            return diagnostics
        diagnostics.update(
            {
                "status": "inserted",
                "episode_key": episode,
                "setup_family": family,
                "observed_at": observed.isoformat(),
                "decision_at": timing.get("decision_at"),
                "publication_confirmed_at": timing.get("publication_confirmed_at"),
                "activation_at": timing.get("activation_at"),
                "execution_start_at": timing.get("execution_start_at"),
                "evidence_identity": evidence_id.public_identity(identity),
            }
        )
        return diagnostics
    except Exception as exc:
        diagnostics.update({"status": "error", "reason": str(exc)[:240]})
        core.logger.warning("Live Trader v83 forward-learning fallback failed: %s", exc)
        return diagnostics


def _matching_zone(state: dict[str, Any], bias: str) -> dict[str, Any] | None:
    """Return a quality matching zone for research without copying the live distance gate.

    Shadow research exists to measure whether distance-to-zone actually adds value.
    Requiring the shadow recorder to pass a distance gate before it can collect
    evidence makes that question untestable and can starve forward research for
    entire trading days. The user-facing/live policy remains unchanged.
    """
    zones = dict(state.get("zones") or {})
    items = [
        dict(item or {})
        for item in list(zones.get("demand" if bias == "bullish" else "supply") or [])
        if isinstance(item, dict)
    ]
    eligible = [item for item in items if _num(item.get("quality")) >= SHADOW_MIN_ZONE_QUALITY]
    if not eligible:
        return None

    # Prefer the nearest quality zone for research. This is deliberately separate
    # from the live policy, which keeps its existing ranked/preferred-zone rules.
    eligible.sort(
        key=lambda item: (
            _num(item.get("distance_atr"), 999.0),
            -_num(item.get("quality")),
        )
    )
    return eligible[0]


def _trade_geometry(
    *,
    side: str,
    order_type: str,
    entry: float,
    stop: float,
    target_r: float,
    variant: str,
) -> dict[str, Any] | None:
    risk = abs(entry - stop)
    if entry <= 0 or stop <= 0 or risk <= 0:
        return None
    target = entry + risk * target_r if side == "BUY" else entry - risk * target_r
    if target <= 0:
        return None
    return {
        "action": f"SHADOW {side}",
        "side": side,
        "order_type": order_type,
        "entry": round(entry, 3),
        "stop": round(stop, 3),
        "target": round(target, 3),
        "risk_reward": round(target_r, 2),
        "confidence": None,
        "manual_only": True,
        "automatic_order_placement": False,
        "shadow_only": True,
        "shadow_variant": variant,
        "reason": "Research-only candidate. Never publish or execute this order from the Live Trader UI.",
        "shadow_distance_gate_applied": False,
    }


def _shadow_candidates(state: dict[str, Any]) -> list[dict[str, Any]]:
    bias = str((state.get("bias") or {}).get("overall") or "neutral").lower()
    if bias not in {"bullish", "bearish"}:
        return []
    zone = _matching_zone(state, bias)
    if zone is None:
        return []

    price = _num(state.get("price"))
    atr = max(_num((state.get("market") or {}).get("atr")), 0.01)
    if price <= 0:
        return []
    side = "BUY" if bias == "bullish" else "SELL"
    zone_low = _num(zone.get("low"))
    zone_high = _num(zone.get("high"))
    if zone_low <= 0 or zone_high <= 0 or zone_high < zone_low:
        return []

    candidates: list[dict[str, Any]] = []

    # Variant 1: immediate market probe. It is deliberately shadow-only and is
    # useful for learning whether waiting for retracement adds value.
    market_stop = zone_low - 0.20 * atr if side == "BUY" else zone_high + 0.20 * atr
    market_risk = abs(price - market_stop)
    if market_risk < 0.35 * atr or market_risk > 3.0 * atr:
        market_stop = price - 0.85 * atr if side == "BUY" else price + 0.85 * atr
    market = _trade_geometry(
        side=side,
        order_type="market",
        entry=price,
        stop=market_stop,
        target_r=SHADOW_TARGET_R,
        variant="market_probe",
    )
    if market:
        candidates.append(market)

    # Variant 2: first-touch retracement into the matching zone.
    if side == "BUY" and zone_high < price:
        limit = _trade_geometry(
            side=side,
            order_type="buy_limit",
            entry=zone_high,
            stop=zone_low - 0.20 * atr,
            target_r=SHADOW_TARGET_R,
            variant="zone_touch_limit",
        )
        if limit:
            candidates.append(limit)
    elif side == "SELL" and zone_low > price:
        limit = _trade_geometry(
            side=side,
            order_type="sell_limit",
            entry=zone_low,
            stop=zone_high + 0.20 * atr,
            target_r=SHADOW_TARGET_R,
            variant="zone_touch_limit",
        )
        if limit:
            candidates.append(limit)

    # Variant 3: simple momentum confirmation. This is intentionally generic so
    # EVE can compare confirmation against market/zone-touch execution without
    # weakening the much stricter user-facing confirmation policy.
    if side == "BUY":
        entry = price + 0.15 * atr
        stop = price - 0.85 * atr
        order_type = "buy_stop"
    else:
        entry = price - 0.15 * atr
        stop = price + 0.85 * atr
        order_type = "sell_stop"
    confirm = _trade_geometry(
        side=side,
        order_type=order_type,
        entry=entry,
        stop=stop,
        target_r=SHADOW_TARGET_R,
        variant="momentum_confirmation",
    )
    if confirm:
        candidates.append(confirm)

    return candidates


def _shadow_ids(state: dict[str, Any], variant: str) -> tuple[str, str]:
    family = str(state.get("setup_family") or state.get("setup_signature") or "unknown")
    as_of = str(state.get("as_of") or "")
    day = as_of[:10] if len(as_of) >= 10 else core.utc_now().date().isoformat()
    session = str((state.get("market") or {}).get("session") or "unknown")
    symbol = str(state.get("symbol") or "XAU/USD")
    shadow_family = hashlib.sha1(f"{family}|{variant}".encode()).hexdigest()[:20]
    episode = hashlib.sha1(f"{symbol}|{day}|{session}|{family}|{variant}".encode()).hexdigest()[:24]
    return shadow_family, episode


async def _record_shadow_variants(self: core.LiveTrader, state: dict[str, Any]) -> dict[str, Any]:
    observed = _recent_observation_time(state)
    if observed is None:
        return {"status": "skipped", "reason": "no_recent_connected_observation"}
    session = session_gate._session_status()
    if not bool(session.get("open")):
        return {"status": "skipped", "reason": "outside_user_facing_trade_window"}

    bucket = observed.replace(minute=(observed.minute // 5) * 5, second=0, microsecond=0)
    if getattr(self, "_shadow_last_bucket_v83", None) == bucket:
        return {"status": "throttled", "bucket": bucket.isoformat()}
    self._shadow_last_bucket_v83 = bucket

    candidates = _shadow_candidates(state)
    if not candidates:
        return {"status": "skipped", "reason": "no_shadow_candidate"}

    inserted = 0
    existing_count = 0
    errors: list[str] = []
    activated: list[dict[str, Any]] = []
    for trade in candidates:
        variant = str(trade.get("shadow_variant") or "unknown")
        family, episode = _shadow_ids(state, variant)
        identity = _shadow_identity(self, variant)
        try:
            await evidence_id.ensure_registered(self.repo, identity)
            existing = await self.repo.client.get(
                "live_trader_opinions",
                params={
                    "select": "id",
                    "learning_version": f"eq.{SHADOW_VERSION}",
                    "cohort_id": f"eq.{identity['cohort_id']}",
                    "setup_family": f"eq.{family}",
                    "episode_key": f"eq.{episode}",
                    "limit": "1",
                },
            )
            if existing:
                existing_count += 1
                continue

            decision_at = core.utc_now()
            descriptor = dict(state.get("setup_family_descriptor") or {})
            descriptor["shadow_variant"] = variant
            market_state = {
                "market": state.get("market"),
                "bias": state.get("bias"),
                "liquidity": state.get("liquidity"),
                "setup_family_descriptor": descriptor,
                "shadow_research": {
                    "version": VERSION,
                    "variant": variant,
                    "publication_authority": False,
                    "visible_trade_gate_unchanged": True,
            "shadow_net_cost_model_version": cost_model.COST_MODEL_VERSION,
                    "market_observed_at": observed.isoformat(),
                    "timing_contract_version": hardening.TIMING_CONTRACT_VERSION,
                    "evidence_identity": evidence_id.public_identity(identity),
                },
            }
            row, timing = await hardening._insert_timed_forward_opinion(
                self,
                {
                    "observed_at": observed.isoformat(),
                    "symbol": self.symbol,
                    "price": state.get("price"),
                    "bias": (state.get("bias") or {}).get("overall"),
                    "confidence": (state.get("bias") or {}).get("confidence"),
                    "horizon_minutes": self.settings.live_trader_learning_horizon_minutes,
                    "setup_signature": family,
                    "setup_family": family,
                    "episode_key": episode,
                    "learning_version": SHADOW_VERSION,
                    "independent_sample": False,
                    "zones": state.get("zones") or {},
                    "trade_idea": evidence_id.attach_trade(trade, identity),
                    "opinion_text": "Research-only shadow trade; never shown as a Live Trader recommendation.",
                    "status": "open",
                    **evidence_id.row_columns(identity),
                },
                observed=observed,
                market_state=market_state,
                decision_at=decision_at,
            )
            if row is None or not timing.get("activation_at"):
                errors.append(f"{variant}: not_durably_activated")
                continue
            inserted += 1
            activated.append({
                "variant": variant,
                "activation_at": timing.get("activation_at"),
                "execution_start_at": timing.get("execution_start_at"),
                "cohort_id": identity.get("cohort_id"),
            })
        except Exception as exc:
            errors.append(str(exc)[:160])
            core.logger.warning("Live Trader v83 shadow record failed for %s: %s", variant, exc)

    return {
        "status": "ok" if not errors else "partial",
        "inserted": inserted,
        "already_present": existing_count,
        "candidates": len(candidates),
        "errors": errors[:3],
        "bucket": bucket.isoformat(),
        "timing_contract_version": hardening.TIMING_CONTRACT_VERSION,
        "activated": activated,
    }


async def _resolve_shadow_outcomes(self: core.LiveTrader) -> dict[str, Any]:
    now = core.utc_now()
    last = getattr(self, "_shadow_last_resolution_v83", None)
    if isinstance(last, datetime) and now - last < timedelta(seconds=SHADOW_RESOLVE_INTERVAL_SECONDS):
        return {"status": "throttled"}
    self._shadow_last_resolution_v83 = now
    cutoff = now - timedelta(minutes=self.settings.live_trader_learning_horizon_minutes)

    try:
        rows = await self.repo.client.get(
            "live_trader_opinions",
            params={
                "select": (
                    "id,observed_at,price,bias,horizon_minutes,market_state,trade_idea,"
                    "market_observed_at,market_received_at,decision_at,publication_requested_at,"
                    "publication_confirmed_at,activation_at,execution_start_at,timing_contract_version"
                ),
                "learning_version": f"eq.{SHADOW_VERSION}",
                "status": "eq.open",
                "observed_at": f"lte.{cutoff.isoformat()}",
                "order": "observed_at.asc",
                "limit": str(SHADOW_RESOLVE_LIMIT),
            },
        )
    except Exception as exc:
        return {"status": "error", "reason": str(exc)[:240]}

    resolved = 0
    waiting_for_horizon = 0
    for row in rows:
        observed = _parse_time(row.get("observed_at"))
        if observed is None:
            continue
        horizon_minutes = int(_num(row.get("horizon_minutes"), self.settings.live_trader_learning_horizon_minutes))
        path_start, horizon, timing_verified, timing = hardening._execution_window(
            row,
            fallback_observed=observed,
            horizon_minutes=horizon_minutes,
            allow_legacy_fallback=False,
        )
        if not timing_verified:
            continue
        if now < horizon:
            waiting_for_horizon += 1
            continue
        try:
            source_rows = await hardening._source_m1_rows(self, path_start, horizon)
            path = hardening._causal_m1_path(source_rows, path_start, horizon)
            endpoint = path.get("endpoint_price")
            endpoint_time = path.get("endpoint_time")
            endpoint_lag = path.get("endpoint_lag_seconds")
            if endpoint is None or endpoint_time is None or endpoint_lag is None:
                continue
            if float(endpoint_lag) > hardening.MAX_ENDPOINT_LAG_SECONDS:
                continue

            path_complete = (
                path.get("initial_gap_seconds") is not None
                and float(path.get("initial_gap_seconds") or 0.0) <= 1.0
                and int(path.get("gap_count") or 0) == 0
            )
            trade = dict(row.get("trade_idea") or {})
            if path_complete:
                result = v2._trade_path_result(trade, list(path.get("bars") or []), float(endpoint))
            else:
                result = {
                    "entry_triggered": None,
                    "trade_outcome": "insufficient_m1_path",
                    "realised_r": None,
                    "learning_success": None,
                }

            market_state = dict(row.get("market_state") or {})
            market_state["shadow_resolution"] = {
                "version": VERSION,
                "resolved_at": now.isoformat(),
                "path_start_at": path_start.isoformat(),
                "horizon_at": horizon.isoformat(),
                "resolved_price_time": endpoint_time.isoformat(),
                "m1_path_bars": len(path.get("bars") or []),
                "path_complete": path_complete,
                "initial_gap_seconds": path.get("initial_gap_seconds"),
                "gap_count": path.get("gap_count"),
                "endpoint_lag_seconds": endpoint_lag,
                "execution_costs": result.get("execution_costs"),
                **timing,
            }
            await self.repo.client.patch(
                "live_trader_opinions",
                {
                    "status": "resolved",
                    "resolved_at": now.isoformat(),
                    "resolved_price": float(endpoint),
                    "entry_triggered": result.get("entry_triggered"),
                    "trade_outcome": result.get("trade_outcome"),
                    "realised_r": result.get("realised_r"),
                    "gross_realised_r": result.get("gross_realised_r"),
                    "estimated_cost_r": result.get("estimated_cost_r"),
                    "net_realised_r": result.get("net_realised_r"),
                    "net_learning_success": result.get("net_learning_success"),
                    "cost_model_version": result.get("cost_model_version"),
                    "execution_costs": result.get("execution_costs"),
                    "learning_success": result.get("learning_success"),
                    "market_state": market_state,
                },
                filters={"id": f"eq.{row.get('id')}"},
            )
            resolved += 1
        except Exception as exc:
            core.logger.warning("Live Trader v83 shadow resolution failed: %s", exc)
    return {
        "status": "ok",
        "resolved": resolved,
        "eligible": len(rows),
        "waiting_for_activation_horizon": waiting_for_horizon,
        "timing_contract_version": hardening.TIMING_CONTRACT_VERSION,
    }


def _trade_skill_from_reviews(
    reviews: list[dict[str, Any]],
    *,
    cohort_id: str | None = None,
) -> dict[str, Any]:
    verified = [
        row for row in reviews
        if str(row.get("cost_model_version") or "") == cost_model.COST_MODEL_VERSION
        and bool(row.get("triggered"))
        and row.get("net_realised_r") is not None
    ]
    n = len(verified)
    values = [_num(row.get("net_realised_r")) for row in verified]
    total_r = sum(values)
    avg_r = total_r / n if n else 0.0
    wins = sum(1 for value in values if value > 0)
    losses = sum(1 for value in values if value < 0)
    breakeven = n - wins - losses
    win_rate = wins / n if n else 0.0

    # Keep the legacy display score for continuity, but never use it as proof.
    performance = core.clamp((avg_r + 0.25) / 0.75, 0.0, 1.0)
    win_component = core.clamp(win_rate / 0.55, 0.0, 1.0)
    evidence = min(1.0, n / 30.0)
    score = 10.0 * (0.55 * performance + 0.25 * win_component + 0.20 * evidence)
    if n < 10:
        score = min(score, 3.0)
    elif n < 30:
        score = min(score, 6.5)
    score = round(core.clamp(score, 0.0, 10.0), 2)

    quality_assessment = quality.evaluate_published_paper(verified, cohort_id=cohort_id)
    forward_net_supported = quality_assessment.get("forward_net_supported") is True
    grade = str(quality_assessment.get("grade") or "UNPROVEN")
    qualification_consistent = (grade == "FORWARD_NET_SUPPORTED") == forward_net_supported
    if not qualification_consistent:
        # Fail closed if qualification metadata ever becomes contradictory.
        forward_net_supported = False
        grade = "QUALIFICATION_INCONSISTENT"

    legacy_triggered = [
        row for row in reviews
        if bool(row.get("triggered"))
        and str(row.get("cost_model_version") or "") != cost_model.COST_MODEL_VERSION
    ]
    return {
        "version": VERSION,
        "score": score,
        "score_is_not_edge_probability": True,
        "grade": grade,
        "published_triggered": n,
        "legacy_triggered_not_counted": len(legacy_triggered),
        "wins": wins,
        "losses": losses,
        "breakeven": breakeven,
        "total_net_r": round(total_r, 3),
        "average_net_r": round(avg_r, 3) if n else None,
        "total_r": round(total_r, 3),
        "average_r": round(avg_r, 3) if n else None,
        "win_rate": round(win_rate, 3) if n else None,
        "independent_days": quality_assessment.get("independent_days"),
        "independent_weeks": quality_assessment.get("independent_weeks"),
        "one_sided_95pct_day_cluster_lower_bound_r": quality_assessment.get(
            "one_sided_95pct_day_cluster_lower_bound_r"
        ),
        "forward_net_supported": forward_net_supported,
        "support_label_consistent_with_all_quality_gates": qualification_consistent,
        "max_single_day_trigger_share": quality_assessment.get("max_single_day_trigger_share"),
        "failed_quality_gates": quality_assessment.get("failed_quality_gates"),
        "evidence_quality_protocol_version": quality.PUBLISHED_PAPER_PROTOCOL_VERSION,
        "minimum_screening_sample": quality.PUBLISHED_MIN_TRIGGERED,
        "sample_count_alone_never_proves_edge": True,
        "automatic_money_approval": False,
        "cost_model_version": cost_model.COST_MODEL_VERSION,
        "meaning": (
            "Trade Skill counts only current-cohort, cost-verified completed paper campaigns. "
            "Thirty trades is a screening milestone, not proof. Support requires every predeclared quality gate: "
            "independent day/week coverage, the single-day concentration limit, positive net expectancy and a "
            "one-sided day-cluster uncertainty bound above zero. The display score is not a win probability."
        ),
    }


def _shadow_stats(rows: list[dict[str, Any]], current_cohorts: set[str] | None = None) -> dict[str, Any]:
    verified_rows = [
        row for row in rows
        if str(row.get("timing_contract_version") or "") == hardening.TIMING_CONTRACT_VERSION
        and str(row.get("cost_model_version") or "") == cost_model.COST_MODEL_VERSION
        and (
            current_cohorts is None
            or str(row.get("cohort_id") or "") in current_cohorts
        )
    ]
    triggered = [
        row for row in verified_rows
        if row.get("entry_triggered") is True and row.get("net_realised_r") is not None
    ]
    values = [_num(row.get("net_realised_r")) for row in triggered]
    total_r = sum(values)
    wins = sum(1 for value in values if value > 0)
    losses = sum(1 for value in values if value < 0)
    return {
        "resolved": len(verified_rows),
        "legacy_unverified_resolved": max(0, len(rows) - len(verified_rows)),
        "triggered": len(triggered),
        "wins": wins,
        "losses": losses,
        "total_net_r": round(total_r, 3),
        "average_net_r": round(total_r / len(triggered), 3) if triggered else None,
        "total_r": round(total_r, 3),
        "average_r": round(total_r / len(triggered), 3) if triggered else None,
        "cost_model_version": cost_model.COST_MODEL_VERSION,
        "research_only": True,
        "publication_authority": False,
    }


async def _trade_skill(self: core.LiveTrader) -> dict[str, Any]:
    now = core.utc_now()
    published_identity = evidence_id.published_campaign_identity(
        self.settings,
        learning_version="eve-live-published-paper-campaign-v1",
    )
    shadow_identities = [_shadow_identity(self, key) for key in ("market_probe", "zone_touch_limit", "momentum_confirmation")]
    current_shadow_cohorts = {str(item["cohort_id"]) for item in shadow_identities}
    cached_at = getattr(self, "_trade_skill_cache_at_v83", None)
    cached = getattr(self, "_trade_skill_cache_v83", None)
    if isinstance(cached_at, datetime) and isinstance(cached, dict):
        if now - cached_at < timedelta(seconds=TRADE_SKILL_CACHE_SECONDS):
            return dict(cached)

    try:
        reviews = await self.repo.client.get(
            "live_trader_trade_reviews",
            params={
                "select": "triggered,realised_r,gross_realised_r,estimated_cost_r,net_realised_r,cost_model_version,outcome,completed_at",
                "symbol": f"eq.{self.symbol}",
                "cohort_id": f"eq.{published_identity['cohort_id']}",
                "order": "completed_at.desc",
                "limit": "500",
            },
        )
    except Exception:
        reviews = []
    try:
        shadow = await self.repo.client.get(
            "live_trader_opinions",
            params={
                "select": "entry_triggered,realised_r,gross_realised_r,estimated_cost_r,net_realised_r,cost_model_version,trade_outcome,observed_at,timing_contract_version,cohort_id",
                "learning_version": f"eq.{SHADOW_VERSION}",
                "status": "eq.resolved",
                "order": "observed_at.desc",
                "limit": "2000",
            },
        )
    except Exception:
        shadow = []

    result = _trade_skill_from_reviews(
        list(reviews),
        cohort_id=str(published_identity.get("cohort_id") or "") or None,
    )
    result["evidence_identity"] = evidence_id.public_identity(published_identity)
    result["shadow_research"] = _shadow_stats(list(shadow), current_shadow_cohorts)
    result["shadow_research"]["current_cohort_ids"] = sorted(current_shadow_cohorts)
    self._trade_skill_cache_at_v83 = now
    self._trade_skill_cache_v83 = dict(result)
    return result


async def _refresh_state_v83(self: core.LiveTrader, *, force_rows: bool = False) -> dict[str, Any]:
    state = dict(await _current_refresh_state(self, force_rows=force_rows))
    forward = await _ensure_forward_observation(self, state)
    shadow = await _record_shadow_variants(self, state)
    resolution = await _resolve_shadow_outcomes(self)
    diagnostics = dict(state.get("forward_learning_health") or {})
    diagnostics.update(
        {
            "version": VERSION,
            "forward": forward,
            "shadow_recording": shadow,
            "shadow_resolution": resolution,
            "visible_trade_gate_unchanged": True,
            "shadow_trades_never_published": True,
        }
    )
    state["forward_learning_health"] = diagnostics
    self._latest_state = state
    return state


async def _learning_summary_v83(self: core.LiveTrader) -> dict[str, Any]:
    summary = dict(await _current_learning_summary(self))
    summary["trade_skill"] = await _trade_skill(self)
    summary["forward_learning_health"] = dict((self._latest_state or {}).get("forward_learning_health") or {})
    summary["system_maturity_note"] = (
        "The existing intelligence index measures architecture and evidence maturity. It is not the Trade Skill score."
    )
    return summary


def _runtime_status_v83(self: core.LiveTrader) -> dict[str, Any]:
    status = dict(_current_runtime_status(self))
    status.update(
        {
            "forward_shadow_learning_version": VERSION,
            "shadow_learning_version": SHADOW_VERSION,
            "published_evidence_quality_protocol_version": quality.PUBLISHED_PAPER_PROTOCOL_VERSION,
            "published_sample_count_alone_never_proves_edge": True,
            "forward_learning_self_healing": True,
            "shadow_trades_publication_authority": False,
            "visible_trade_gate_unchanged": True,
        }
    )
    return status


core.LiveTrader.refresh_state = _refresh_state_v83  # type: ignore[method-assign]
core.LiveTrader.learning_summary = _learning_summary_v83  # type: ignore[method-assign]
core.LiveTrader.runtime_status = _runtime_status_v83  # type: ignore[method-assign]
