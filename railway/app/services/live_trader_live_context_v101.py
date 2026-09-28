from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services import live_trader as core
from app.services import live_trader_context_contract as contract
from app.services import live_trader_trade_lock_v28 as lock
from app.services.m5_foundation import LOOKBACK_BARS, build_m5_snapshot
from app.services.multitimeframe import CompletedCandleIndex, aggregate_m30, as_utc, build_fabric_context
from app.services.repository import SourceRepository

logger = logging.getLogger(__name__)

VERSION = contract.LIVE_CONTEXT_VERSION
PATCH_VERSION = "eve-live-context-freshness-v101-completion-guard-v1"

_current_load_rows = core.LiveTrader._load_rows
_current_bias = core.LiveTrader._bias
_current_runtime_status = core.LiveTrader.runtime_status
_current_maybe_persist_state = core.LiveTrader._maybe_persist_state


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


def _latest_row_time(rows: list[dict[str, Any]]) -> datetime | None:
    if not rows:
        return None
    return _parse_time(rows[-1].get("candle_time"))


def _completed_m5_start(reference: datetime) -> datetime:
    reference = reference.astimezone(timezone.utc)
    floored = reference.replace(
        minute=(reference.minute // 5) * 5,
        second=0,
        microsecond=0,
    )
    return floored - timedelta(minutes=5)


def _decision_time(row: dict[str, Any] | None) -> datetime | None:
    """Return the explicit causal decision timestamp stored with an M5 snapshot.

    Live freshness never invents this timestamp from candle_time. Missing or
    malformed decision timestamps are unverifiable and therefore fail closed.
    """
    if not row:
        return None
    context = dict(row.get("mtf_context") or {})
    return _parse_time(context.get("decision_time"))


def _row_completion_validation(
    row: dict[str, Any],
    reference: datetime | None,
) -> tuple[bool, str | None, datetime | None, datetime | None]:
    if reference is None:
        return False, "missing_live_reference", None, None

    stamp = _parse_time(row.get("candle_time"))
    if stamp is None:
        return False, "missing_or_invalid_candle_time", None, None

    context = dict(row.get("mtf_context") or {})
    decision = _parse_time(context.get("decision_time"))
    if decision is None:
        return False, "missing_or_invalid_decision_time", stamp, None

    expected_decision = stamp + timedelta(minutes=5)
    if decision != expected_decision:
        return False, "decision_time_not_exactly_m5_close", stamp, decision

    signal_time = context.get("signal_time")
    if signal_time not in (None, ""):
        parsed_signal = _parse_time(signal_time)
        if parsed_signal is None or parsed_signal != stamp:
            return False, "signal_time_mismatch", stamp, decision

    completed_through = _completed_m5_start(reference)
    if stamp > completed_through:
        return False, "forming_or_future_m5_candle", stamp, decision
    if decision > reference:
        return False, "decision_time_after_live_reference", stamp, decision
    return True, None, stamp, decision


def _validate_context_rows(
    rows: list[dict[str, Any]],
    reference: datetime | None,
) -> tuple[bool, str | None]:
    if reference is None:
        return False, "missing_live_reference"
    if not rows:
        return False, "empty_context"

    previous: datetime | None = None
    for index, row in enumerate(rows):
        valid, reason, stamp, _ = _row_completion_validation(row, reference)
        if not valid:
            return False, f"row_{index}:{reason}"
        if stamp is None:
            return False, f"row_{index}:missing_or_invalid_candle_time"
        if previous is not None and stamp <= previous:
            return False, f"row_{index}:non_monotonic_candle_time"
        previous = stamp
    return True, None


def _context_lag_minutes(rows: list[dict[str, Any]], reference: datetime | None) -> float | None:
    if reference is None or not rows:
        return None
    valid, _, _, decision = _row_completion_validation(rows[-1], reference)
    if not valid or decision is None:
        return None
    return (reference - decision).total_seconds() / 60.0


async def _persistent_fabric_watermark(self: core.LiveTrader) -> datetime | None:
    rows = await self.repo.client.get(
        "m5_research_snapshots",
        params={
            "select": "candle_time",
            "symbol": f"eq.{self.symbol}",
            "order": "candle_time.desc",
            "limit": "1",
        },
    )
    return _parse_time((rows[0] or {}).get("candle_time")) if rows else None


async def _load_persistent_rows_direct(self: core.LiveTrader) -> list[dict[str, Any]]:
    rows = await self.repo.client.get(
        "m5_research_snapshots",
        params={
            "select": (
                "candle_time,open,high,low,close,atr_14,session,regime,direction,"
                "return_12_pct,return_48_pct,mtf_context,outcome_complete"
            ),
            "symbol": f"eq.{self.symbol}",
            "order": "candle_time.desc",
            "limit": "720",
        },
    )
    rows.reverse()
    return list(rows)


async def _fetch_range(
    source: SourceRepository,
    interval: str,
    start: datetime,
    end: datetime,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        page = await source.fetch_candles_page(
            source.settings.source_symbol,
            interval,
            after=cursor,
            date_from=start.isoformat() if cursor is None else None,
            date_to=end.isoformat(),
            limit=1000,
        )
        if not page:
            break
        rows.extend(page)
        cursor = str(page[-1].get("candle_time") or "")
        if len(page) < 1000:
            break
    return rows


async def _fetch_m5_after(
    source: SourceRepository,
    after: datetime,
    completed_through: datetime,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    cursor = after.isoformat()
    while len(rows) < contract.MAX_OVERLAY_M5_ROWS:
        page = await source.fetch_candles_page(
            source.settings.source_symbol,
            "5min",
            after=cursor,
            date_to=completed_through.isoformat(),
            limit=min(1000, contract.MAX_OVERLAY_M5_ROWS - len(rows)),
        )
        if not page:
            break
        rows.extend(page)
        cursor = str(page[-1].get("candle_time") or "")
        if len(page) < 1000:
            break

    clean = []
    for row in rows:
        stamp = _parse_time(row.get("candle_time"))
        if stamp is None or stamp <= after or stamp > completed_through:
            continue
        clean.append(dict(row))
    clean.sort(key=lambda row: str(row.get("candle_time") or ""))
    return clean


def _m1_buckets(rows: list[dict[str, Any]]) -> dict[datetime, list[dict[str, Any]]]:
    buckets: dict[datetime, list[dict[str, Any]]] = {}
    for row in rows:
        stamp = _parse_time(row.get("candle_time"))
        if stamp is None:
            continue
        bucket = stamp.replace(minute=(stamp.minute // 5) * 5, second=0, microsecond=0)
        buckets.setdefault(bucket, []).append(row)
    return buckets


def _diagnostic(
    *,
    rows: list[dict[str, Any]],
    reference: datetime | None,
    persistent_latest: datetime | None,
    overlay_rows: int,
    status: str,
    error: str | None = None,
) -> dict[str, Any]:
    effective_latest = _latest_row_time(rows)
    context_valid, validation_error = _validate_context_rows(rows, reference)
    lag = _context_lag_minutes(rows, reference)
    fresh = bool(
        context_valid
        and lag is not None
        and 0.0 <= lag <= contract.MAX_CONTEXT_LAG_MINUTES
    )
    explicit_decision = _decision_time(rows[-1]) if rows else None
    return {
        "version": VERSION,
        "patch_version": PATCH_VERSION,
        "contract_version": contract.CONTEXT_CONTRACT_VERSION,
        "status": status,
        "source": contract.SOURCE_NAME,
        "live_tick_at": reference.isoformat() if reference is not None else None,
        "persistent_latest_m5": persistent_latest.isoformat() if persistent_latest is not None else None,
        "effective_latest_m5": effective_latest.isoformat() if effective_latest is not None else None,
        "effective_decision_time": explicit_decision.isoformat() if explicit_decision is not None else None,
        "context_lag_minutes": round(lag, 3) if lag is not None else None,
        "max_context_lag_minutes": contract.MAX_CONTEXT_LAG_MINUTES,
        "overlay_rows": int(overlay_rows),
        "context_valid": bool(context_valid),
        "validation_error": validation_error,
        "fresh": fresh,
        "fail_closed": True,
        "persistent_research_fabric_required_for_live_freshness": False,
        "error": error,
    }


async def _overlay_fresh_rows(
    self: core.LiveTrader,
    seed: list[dict[str, Any]],
    reference: datetime,
    persistent_latest: datetime | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    seed_valid, seed_error = _validate_context_rows(seed, reference)
    if not seed_valid:
        raise RuntimeError(f"live_context_seed_invalid:{seed_error}")

    if len(seed) < LOOKBACK_BARS:
        return seed, _diagnostic(
            rows=seed,
            reference=reference,
            persistent_latest=persistent_latest,
            overlay_rows=0,
            status="insufficient_base_history",
        )

    latest = _latest_row_time(seed)
    if latest is None:
        return seed, _diagnostic(
            rows=seed,
            reference=reference,
            persistent_latest=persistent_latest,
            overlay_rows=0,
            status="missing_base_timestamp",
        )

    completed_through = _completed_m5_start(reference)
    if latest >= completed_through:
        return seed, _diagnostic(
            rows=seed,
            reference=reference,
            persistent_latest=persistent_latest,
            overlay_rows=0,
            status="context_current",
        )

    source = getattr(self, "_live_context_source_v101", None)
    if source is None:
        source = SourceRepository(self.settings)
        self._live_context_source_v101 = source

    fresh_m5 = await _fetch_m5_after(source, latest, completed_through)
    if not fresh_m5:
        return seed, _diagnostic(
            rows=seed,
            reference=reference,
            persistent_latest=persistent_latest,
            overlay_rows=0,
            status="source_has_no_new_completed_m5",
        )

    if len(fresh_m5) >= contract.MAX_OVERLAY_M5_ROWS:
        raise RuntimeError("live_context_overlay_row_limit_reached_before_catching_up")

    first_fresh = _parse_time(fresh_m5[0].get("candle_time"))
    last_fresh = _parse_time(fresh_m5[-1].get("candle_time"))
    if first_fresh is None or last_fresh is None:
        raise RuntimeError("live_context_overlay_contains_invalid_m5_timestamp")

    m1_rows = await _fetch_range(source, "1min", first_fresh, last_fresh + timedelta(minutes=5))
    m15_rows = await _fetch_range(source, "15min", first_fresh - timedelta(days=2), reference)
    h1_rows = await _fetch_range(source, "1h", first_fresh - timedelta(days=10), reference)
    h4_rows = await _fetch_range(source, "4h", first_fresh - timedelta(days=40), reference)
    d1_rows = await _fetch_range(source, "1day", first_fresh - timedelta(days=90), reference)

    m30_rows = aggregate_m30([*seed[-720:], *fresh_m5])
    m15_index = CompletedCandleIndex(m15_rows, "15min")
    m30_index = CompletedCandleIndex(m30_rows, "30min")
    h1_index = CompletedCandleIndex(h1_rows, "1h")
    h4_index = CompletedCandleIndex(h4_rows, "4h")
    d1_index = CompletedCandleIndex(d1_rows, "1day")
    m1_by_m5 = _m1_buckets(m1_rows)

    combined = list(seed)
    built = 0
    for current in fresh_m5:
        stamp = _parse_time(current.get("candle_time"))
        if stamp is None:
            continue
        previous = combined[-LOOKBACK_BARS:]
        if len(previous) < LOOKBACK_BARS:
            raise RuntimeError("live_context_overlay_lost_required_m5_lookback")
        fabric = build_fabric_context(
            current,
            m1_rows=m1_by_m5.get(stamp, []),
            m15_index=m15_index,
            m30_index=m30_index,
            h1_index=h1_index,
            h4_index=h4_index,
            d1_index=d1_index,
        )
        combined.append(
            build_m5_snapshot(
                self.symbol,
                previous,
                current,
                [],
                fabric,
            )
        )
        built += 1

    # Live Trader only uses a rolling context window. Keeping 720 observations
    # bounds resident memory while preserving the existing structural history.
    combined = combined[-720:]
    combined_valid, combined_error = _validate_context_rows(combined, reference)
    if not combined_valid:
        raise RuntimeError(f"live_context_overlay_invalid:{combined_error}")
    return combined, _diagnostic(
        rows=combined,
        reference=reference,
        persistent_latest=persistent_latest,
        overlay_rows=built,
        status="fresh_source_overlay_applied" if built else "source_overlay_empty",
    )


async def _load_rows_v101(self: core.LiveTrader, force: bool = False) -> list[dict[str, Any]]:
    persistent = list(await _current_load_rows(self, force=force))
    try:
        persistent_latest = await _persistent_fabric_watermark(self)
        self._live_context_persistent_watermark_v101 = persistent_latest
        persistent_watermark_error = None
    except Exception as exc:
        persistent_latest = getattr(self, "_live_context_persistent_watermark_v101", None)
        persistent_watermark_error = str(exc)[:500]

    cached = list(getattr(self, "_live_context_rows_v101", None) or [])
    cached_latest = _latest_row_time(cached)
    seed = cached if cached_latest is not None and (
        _latest_row_time(persistent) is None or cached_latest > _latest_row_time(persistent)
    ) else persistent

    now = core.utc_now()
    last_poll = getattr(self, "_live_context_polled_at_v101", None)
    reference = _parse_time(getattr(self, "last_tick_at", None)) or now
    if (
        not force
        and seed
        and isinstance(last_poll, datetime)
        and now - last_poll < timedelta(seconds=contract.SOURCE_POLL_SECONDS)
    ):
        diagnostic = _diagnostic(
            rows=seed,
            reference=reference,
            persistent_latest=persistent_latest,
            overlay_rows=0,
            status="cached_live_context",
        )
        diagnostic["persistent_watermark_error"] = persistent_watermark_error
        self._live_context_diagnostic_v101 = diagnostic
        self._rows = seed
        return seed

    try:
        seed_valid, _ = _validate_context_rows(seed, reference)
        if not seed_valid:
            # Recover from a poisoned ephemeral/core cache only by re-reading the
            # persistent snapshot table. The invalid row is never trusted.
            seed = await _load_persistent_rows_direct(self)
        merged, diagnostic = await _overlay_fresh_rows(self, seed, reference, persistent_latest)
    except Exception as exc:
        logger.warning("Live Trader fresh-context overlay failed safely: %s", exc)
        merged = seed
        diagnostic = _diagnostic(
            rows=seed,
            reference=reference,
            persistent_latest=persistent_latest,
            overlay_rows=0,
            status="source_overlay_failed",
            error=str(exc)[:500],
        )

    diagnostic["persistent_watermark_error"] = persistent_watermark_error
    self._live_context_polled_at_v101 = now
    self._live_context_rows_v101 = list(merged)
    self._live_context_diagnostic_v101 = dict(diagnostic)
    self._rows = list(merged)
    self._rows_loaded_at = now
    return list(merged)


def _bias_v101(self: core.LiveTrader, latest: dict[str, Any]) -> tuple[dict[str, Any], float]:
    bias, score = _current_bias(self, latest)
    bias = dict(bias)
    data_quality = dict(bias.get("data_quality") or {})

    reference = _parse_time(getattr(self, "last_tick_at", None))
    lag = _context_lag_minutes([latest], reference)
    feed_fresh = bool(reference is not None and getattr(self, "_feed_is_fresh", lambda: False)())
    row_valid, row_error = _validate_context_rows([latest], reference)
    prior_diagnostic = dict(getattr(self, "_live_context_diagnostic_v101", {}) or {})
    diagnostic_fresh = prior_diagnostic.get("fresh") is True
    blocked = bool(
        feed_fresh
        and (
            not row_valid
            or lag is None
            or lag < 0.0
            or lag > contract.MAX_CONTEXT_LAG_MINUTES
            or not diagnostic_fresh
        )
    )

    diagnostic = prior_diagnostic
    diagnostic.update(
        {
            "version": VERSION,
            "patch_version": PATCH_VERSION,
            "context_lag_minutes": round(lag, 3) if lag is not None else None,
            "max_context_lag_minutes": contract.MAX_CONTEXT_LAG_MINUTES,
            "context_valid": bool(row_valid and diagnostic.get("context_valid", True)),
            "validation_error": row_error or diagnostic.get("validation_error"),
            "fresh": False if blocked else (diagnostic.get("fresh") if not feed_fresh else True),
            "feed_fresh": feed_fresh,
        }
    )
    self._live_context_diagnostic_v101 = diagnostic

    data_quality["live_context_freshness_version"] = VERSION
    data_quality["live_context_patch_version"] = PATCH_VERSION
    data_quality["live_context_lag_minutes"] = diagnostic.get("context_lag_minutes")
    data_quality["live_context_max_lag_minutes"] = contract.MAX_CONTEXT_LAG_MINUTES
    data_quality["live_context_valid"] = diagnostic.get("context_valid")
    data_quality["live_context_validation_error"] = diagnostic.get("validation_error")
    data_quality["live_context_stale"] = blocked
    data_quality["live_context_fail_closed"] = True

    if blocked:
        bias["overall"] = "neutral"
        bias["raw_score"] = 0.0
        bias["confidence"] = min(int(core.number(bias.get("confidence"), 40)), 50)
        data_quality["trade_bias_blocked"] = True
        if not row_valid:
            reason = f"Live M5/MTF context failed completion validation: {row_error}."
        elif lag is None:
            reason = "Live M5/MTF context has no verifiable decision timestamp."
        elif lag < 0.0:
            reason = "Live M5/MTF context decision timestamp is in the future."
        elif lag > contract.MAX_CONTEXT_LAG_MINUTES:
            reason = (
                f"Live M5/MTF context is {lag:.1f} minutes behind the live price feed; "
                f"maximum allowed lag is {contract.MAX_CONTEXT_LAG_MINUTES:.1f} minutes."
            )
        else:
            reason = "Live M5/MTF context failed the end-to-end freshness diagnostic."
        data_quality["live_context_block_reason"] = reason
        score = 0.0

    bias["data_quality"] = data_quality
    return bias, score


def _decorate_state(self: core.LiveTrader, state: dict[str, Any]) -> None:
    diagnostic = dict(getattr(self, "_live_context_diagnostic_v101", {}) or {})
    state["live_context_freshness"] = diagnostic
    market = dict(state.get("market") or {})
    market["context_source"] = contract.SOURCE_NAME
    market["context_freshness_version"] = VERSION
    market["context_lag_minutes"] = diagnostic.get("context_lag_minutes")
    market["context_fresh"] = diagnostic.get("fresh")
    state["market"] = market
    safety = dict(state.get("safety") or {})
    safety["live_context_freshness_required"] = True
    safety["live_context_max_lag_minutes"] = contract.MAX_CONTEXT_LAG_MINUTES
    state["safety"] = safety


async def _maybe_persist_state_v101(self: core.LiveTrader, state: dict[str, Any]) -> None:
    _decorate_state(self, state)
    await _current_maybe_persist_state(self, state)


def _runtime_status_v101(self: core.LiveTrader) -> dict[str, Any]:
    status = dict(_current_runtime_status(self))
    status.update(
        {
            "live_context_freshness_version": VERSION,
            "live_context_patch_version": PATCH_VERSION,
            "live_context_contract": contract.definition(),
            "live_context_freshness": dict(getattr(self, "_live_context_diagnostic_v101", {}) or {}),
        }
    )
    return status


core.LiveTrader._load_rows = _load_rows_v101  # type: ignore[method-assign]
core.LiveTrader._bias = _bias_v101  # type: ignore[method-assign]
core.LiveTrader._maybe_persist_state = _maybe_persist_state_v101  # type: ignore[method-assign]
core.LiveTrader.runtime_status = _runtime_status_v101  # type: ignore[method-assign]
# Preserve the established compatibility alias contract used by earlier audited wrappers.
lock._maybe_persist_state_v28 = _maybe_persist_state_v101
