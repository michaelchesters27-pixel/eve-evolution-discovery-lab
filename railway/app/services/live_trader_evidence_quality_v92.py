from __future__ import annotations

import hashlib
import math
import random
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

PROTOCOL_VERSION = "eve-live-evidence-quality-v1"
POLICY_LAB_PROTOCOL_VERSION = "eve-live-policy-lab-evidence-quality-v1"
PUBLISHED_PAPER_PROTOCOL_VERSION = "eve-live-published-paper-evidence-quality-v2"
HISTORICAL_PROXY_PROTOCOL_VERSION = "eve-live-historical-proxy-screening-v1"

FAMILY_ALPHA = 0.05
POLICY_LAB_COMPARISONS = 7
POLICY_LAB_MIN_TRIGGERED = 30
POLICY_LAB_MIN_INDEPENDENT_DAYS = 20
POLICY_LAB_MIN_INDEPENDENT_WEEKS = 4
POLICY_LAB_MIN_NET_EXPECTANCY_R = 0.10
POLICY_LAB_MAX_SINGLE_DAY_TRIGGER_SHARE = 0.25
BOOTSTRAP_DRAWS = 5000

PUBLISHED_MIN_TRIGGERED = 30
PUBLISHED_MIN_INDEPENDENT_DAYS = 20
PUBLISHED_MIN_INDEPENDENT_WEEKS = 4
PUBLISHED_MAX_SINGLE_DAY_TRIGGER_SHARE = 0.25


def policy_lab_protocol_definition() -> dict[str, Any]:
    return {
        "version": POLICY_LAB_PROTOCOL_VERSION,
        "parent_version": PROTOCOL_VERSION,
        "purpose": "Prospective screening of seven simultaneously observed research policies; never automatic promotion.",
        "primary_metric": "cost_verified_net_realised_r_per_triggered_trade",
        "independence_unit": "UTC calendar day cluster",
        "minimum_triggered": POLICY_LAB_MIN_TRIGGERED,
        "minimum_independent_days": POLICY_LAB_MIN_INDEPENDENT_DAYS,
        "minimum_independent_weeks": POLICY_LAB_MIN_INDEPENDENT_WEEKS,
        "minimum_net_expectancy_r": POLICY_LAB_MIN_NET_EXPECTANCY_R,
        "maximum_single_day_trigger_share": POLICY_LAB_MAX_SINGLE_DAY_TRIGGER_SHARE,
        "uncertainty_method": "deterministic UTC-day cluster bootstrap",
        "bootstrap_draws": BOOTSTRAP_DRAWS,
        "family_wise_alpha": FAMILY_ALPHA,
        "simultaneous_policy_count": POLICY_LAB_COMPARISONS,
        "multiplicity_method": "Bonferroni one-sided lower bound",
        "per_policy_alpha": FAMILY_ALPHA / POLICY_LAB_COMPARISONS,
        "candidate_output": "fresh_confirmation_candidate_only",
        "fresh_confirmation_required": True,
        "automatic_promotion": False,
        "selection_cohort_may_confirm_winner": False,
    }


def published_paper_protocol_definition() -> dict[str, Any]:
    return {
        "version": PUBLISHED_PAPER_PROTOCOL_VERSION,
        "parent_version": PROTOCOL_VERSION,
        "purpose": "Assess one frozen published paper policy without treating a raw trade count as proof.",
        "primary_metric": "cost_verified_net_realised_r_per_triggered_trade",
        "independence_unit": "UTC calendar day cluster",
        "minimum_triggered": PUBLISHED_MIN_TRIGGERED,
        "minimum_independent_days": PUBLISHED_MIN_INDEPENDENT_DAYS,
        "minimum_independent_weeks": PUBLISHED_MIN_INDEPENDENT_WEEKS,
        "maximum_single_day_trigger_share": PUBLISHED_MAX_SINGLE_DAY_TRIGGER_SHARE,
        "uncertainty_method": "deterministic UTC-day cluster bootstrap",
        "bootstrap_draws": BOOTSTRAP_DRAWS,
        "one_sided_alpha": FAMILY_ALPHA,
        "required_lower_bound": 0.0,
        "sample_count_alone_never_proves_edge": True,
        "support_label_requires_all_quality_gates": True,
        "automatic_money_approval": False,
    }


def historical_proxy_protocol_definition() -> dict[str, Any]:
    return {
        "version": HISTORICAL_PROXY_PROTOCOL_VERSION,
        "parent_version": PROTOCOL_VERSION,
        "purpose": "Historical screening only; selected archive evidence can never directly promote a live execution policy.",
        "prospective_validation_eligible": False,
        "historical_proxy_may_auto_promote": False,
        "fresh_forward_confirmation_required": True,
    }


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


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _date_key(row: dict[str, Any], time_fields: tuple[str, ...]) -> str | None:
    for field in time_fields:
        parsed = _parse_time(row.get(field))
        if parsed is not None:
            return parsed.date().isoformat()
    return None


def _week_key(day: str) -> str:
    parsed = datetime.fromisoformat(day).date()
    iso = parsed.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _cluster_rows(
    rows: list[dict[str, Any]],
    *,
    value_field: str,
    time_fields: tuple[str, ...],
) -> tuple[list[float], dict[str, list[float]]]:
    values: list[float] = []
    by_day: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        value = row.get(value_field)
        if value is None:
            continue
        day = _date_key(row, time_fields)
        if day is None:
            continue
        score = _num(value)
        values.append(score)
        by_day[day].append(score)
    return values, dict(by_day)


def _seed(label: str, by_day: dict[str, list[float]]) -> int:
    canonical = "|".join(
        [
            PROTOCOL_VERSION,
            label,
            *[
                f"{day}:{','.join(f'{value:.8f}' for value in by_day[day])}"
                for day in sorted(by_day)
            ],
        ]
    )
    return int(hashlib.sha256(canonical.encode()).hexdigest()[:16], 16)


def day_cluster_bootstrap_lower_bound(
    rows: list[dict[str, Any]],
    *,
    value_field: str,
    time_fields: tuple[str, ...],
    alpha: float,
    label: str,
    draws: int = BOOTSTRAP_DRAWS,
) -> float | None:
    _, by_day = _cluster_rows(rows, value_field=value_field, time_fields=time_fields)
    days = sorted(by_day)
    if len(days) < 2 or draws < 100:
        return None

    rng = random.Random(_seed(label, by_day))
    estimates: list[float] = []
    for _ in range(draws):
        total = 0.0
        count = 0
        for _slot in range(len(days)):
            day = days[rng.randrange(len(days))]
            bucket = by_day[day]
            total += sum(bucket)
            count += len(bucket)
        if count:
            estimates.append(total / count)

    if not estimates:
        return None
    estimates.sort()
    index = int(math.floor(max(0.0, min(1.0, alpha)) * (len(estimates) - 1)))
    return round(estimates[index], 5)


def _daily_seed(label: str, daily: list[dict[str, Any]]) -> int:
    canonical = "|".join(
        [
            PROTOCOL_VERSION,
            label,
            *[
                (
                    f"{str(item.get('day') or '')}:"
                    f"{int(_num(item.get('triggered')))}:"
                    f"{_num(item.get('net_r')):.8f}"
                )
                for item in sorted(daily, key=lambda row: str(row.get("day") or ""))
            ],
        ]
    )
    return int(hashlib.sha256(canonical.encode()).hexdigest()[:16], 16)


def day_cluster_bootstrap_lower_bound_from_daily(
    daily: list[dict[str, Any]],
    *,
    alpha: float,
    label: str,
    draws: int = BOOTSTRAP_DRAWS,
) -> float | None:
    clusters = [
        {
            "day": str(item.get("day") or ""),
            "triggered": max(0, int(_num(item.get("triggered")))),
            "net_r": _num(item.get("net_r")),
        }
        for item in daily
        if str(item.get("day") or "") and int(_num(item.get("triggered"))) > 0
    ]
    if len(clusters) < 2 or draws < 100:
        return None

    rng = random.Random(_daily_seed(label, clusters))
    estimates: list[float] = []
    for _ in range(draws):
        total = 0.0
        count = 0
        for _slot in range(len(clusters)):
            item = clusters[rng.randrange(len(clusters))]
            total += float(item["net_r"])
            count += int(item["triggered"])
        if count:
            estimates.append(total / count)

    if not estimates:
        return None
    estimates.sort()
    index = int(math.floor(max(0.0, min(1.0, alpha)) * (len(estimates) - 1)))
    return round(estimates[index], 5)


def evidence_shape_from_daily(daily: list[dict[str, Any]]) -> dict[str, Any]:
    clusters = [
        {
            "day": str(item.get("day") or ""),
            "triggered": max(0, int(_num(item.get("triggered")))),
            "net_r": _num(item.get("net_r")),
        }
        for item in daily
        if str(item.get("day") or "") and int(_num(item.get("triggered"))) > 0
    ]
    clusters.sort(key=lambda item: item["day"])
    n = sum(int(item["triggered"]) for item in clusters)
    total = sum(float(item["net_r"]) for item in clusters)
    days = [str(item["day"]) for item in clusters]
    weeks = sorted({_week_key(day) for day in days})
    max_day_count = max((int(item["triggered"]) for item in clusters), default=0)
    max_day_share = max_day_count / n if n else 0.0
    absolute_total = sum(abs(float(item["net_r"])) for item in clusters)
    max_abs_day_share = (
        max((abs(float(item["net_r"])) for item in clusters), default=0.0) / absolute_total
        if absolute_total > 0
        else 0.0
    )
    return {
        "triggered": n,
        "total_net_r": round(total, 5),
        "net_expectancy_r": round(total / n, 5) if n else None,
        "independent_days": len(days),
        "independent_weeks": len(weeks),
        "max_single_day_trigger_share": round(max_day_share, 5),
        "max_single_day_absolute_r_share": round(max_abs_day_share, 5),
        "first_day": days[0] if days else None,
        "last_day": days[-1] if days else None,
    }


def evaluate_policy_lab_daily_summary(
    daily: list[dict[str, Any]],
    *,
    policy_key: str,
    cohort_id: str | None,
) -> dict[str, Any]:
    protocol = policy_lab_protocol_definition()
    shape = evidence_shape_from_daily(daily)
    lower = day_cluster_bootstrap_lower_bound_from_daily(
        daily,
        alpha=FAMILY_ALPHA / POLICY_LAB_COMPARISONS,
        label=f"policy_lab|{policy_key}|{cohort_id or 'none'}",
    )
    screening_pass = bool(
        shape["triggered"] >= POLICY_LAB_MIN_TRIGGERED
        and shape["net_expectancy_r"] is not None
        and shape["net_expectancy_r"] >= POLICY_LAB_MIN_NET_EXPECTANCY_R
    )
    gates = {
        "minimum_triggered": shape["triggered"] >= POLICY_LAB_MIN_TRIGGERED,
        "minimum_independent_days": shape["independent_days"] >= POLICY_LAB_MIN_INDEPENDENT_DAYS,
        "minimum_independent_weeks": shape["independent_weeks"] >= POLICY_LAB_MIN_INDEPENDENT_WEEKS,
        "minimum_net_expectancy": (
            shape["net_expectancy_r"] is not None
            and shape["net_expectancy_r"] >= POLICY_LAB_MIN_NET_EXPECTANCY_R
        ),
        "single_day_concentration": shape["max_single_day_trigger_share"] <= POLICY_LAB_MAX_SINGLE_DAY_TRIGGER_SHARE,
        "multiplicity_adjusted_lower_bound_positive": lower is not None and lower > 0.0,
    }
    confirmation_candidate = bool(all(gates.values()))
    return {
        "protocol_version": POLICY_LAB_PROTOCOL_VERSION,
        "cohort_id": cohort_id,
        **shape,
        "screening_pass_30_and_mean_only": screening_pass,
        "multiplicity_adjusted_one_sided_lower_bound_r": lower,
        "family_wise_alpha": FAMILY_ALPHA,
        "per_policy_alpha": round(FAMILY_ALPHA / POLICY_LAB_COMPARISONS, 8),
        "simultaneous_policy_count": POLICY_LAB_COMPARISONS,
        "quality_gates": gates,
        "failed_quality_gates": [name for name, passed in gates.items() if not passed],
        "fresh_confirmation_candidate": confirmation_candidate,
        "forward_candidate": confirmation_candidate,
        "fresh_confirmation_required": True,
        "automatic_promotion": False,
        "selection_cohort_may_confirm_winner": False,
        "protocol": protocol,
    }


def evidence_shape(
    rows: list[dict[str, Any]],
    *,
    value_field: str,
    time_fields: tuple[str, ...],
) -> dict[str, Any]:
    values, by_day = _cluster_rows(rows, value_field=value_field, time_fields=time_fields)
    days = sorted(by_day)
    weeks = sorted({_week_key(day) for day in days})
    total = sum(values)
    n = len(values)
    max_day_count = max((len(items) for items in by_day.values()), default=0)
    max_day_share = max_day_count / n if n else 0.0
    day_totals = {day: sum(items) for day, items in by_day.items()}
    absolute_total = sum(abs(value) for value in day_totals.values())
    max_abs_day_share = (
        max((abs(value) for value in day_totals.values()), default=0.0) / absolute_total
        if absolute_total > 0
        else 0.0
    )
    return {
        "triggered": n,
        "total_net_r": round(total, 5),
        "net_expectancy_r": round(total / n, 5) if n else None,
        "independent_days": len(days),
        "independent_weeks": len(weeks),
        "max_single_day_trigger_share": round(max_day_share, 5),
        "max_single_day_absolute_r_share": round(max_abs_day_share, 5),
        "first_day": days[0] if days else None,
        "last_day": days[-1] if days else None,
    }


def evaluate_policy_lab_candidate(
    rows: list[dict[str, Any]],
    *,
    policy_key: str,
    cohort_id: str | None,
) -> dict[str, Any]:
    protocol = policy_lab_protocol_definition()
    shape = evidence_shape(
        rows,
        value_field="net_realised_r",
        time_fields=("observed_at",),
    )
    lower = day_cluster_bootstrap_lower_bound(
        rows,
        value_field="net_realised_r",
        time_fields=("observed_at",),
        alpha=FAMILY_ALPHA / POLICY_LAB_COMPARISONS,
        label=f"policy_lab|{policy_key}|{cohort_id or 'none'}",
    )
    screening_pass = bool(
        shape["triggered"] >= POLICY_LAB_MIN_TRIGGERED
        and shape["net_expectancy_r"] is not None
        and shape["net_expectancy_r"] >= POLICY_LAB_MIN_NET_EXPECTANCY_R
    )
    gates = {
        "minimum_triggered": shape["triggered"] >= POLICY_LAB_MIN_TRIGGERED,
        "minimum_independent_days": shape["independent_days"] >= POLICY_LAB_MIN_INDEPENDENT_DAYS,
        "minimum_independent_weeks": shape["independent_weeks"] >= POLICY_LAB_MIN_INDEPENDENT_WEEKS,
        "minimum_net_expectancy": (
            shape["net_expectancy_r"] is not None
            and shape["net_expectancy_r"] >= POLICY_LAB_MIN_NET_EXPECTANCY_R
        ),
        "single_day_concentration": shape["max_single_day_trigger_share"] <= POLICY_LAB_MAX_SINGLE_DAY_TRIGGER_SHARE,
        "multiplicity_adjusted_lower_bound_positive": lower is not None and lower > 0.0,
    }
    confirmation_candidate = bool(all(gates.values()))
    failed = [name for name, passed in gates.items() if not passed]
    return {
        "protocol_version": POLICY_LAB_PROTOCOL_VERSION,
        "cohort_id": cohort_id,
        **shape,
        "screening_pass_30_and_mean_only": screening_pass,
        "multiplicity_adjusted_one_sided_lower_bound_r": lower,
        "family_wise_alpha": FAMILY_ALPHA,
        "per_policy_alpha": round(FAMILY_ALPHA / POLICY_LAB_COMPARISONS, 8),
        "simultaneous_policy_count": POLICY_LAB_COMPARISONS,
        "quality_gates": gates,
        "failed_quality_gates": failed,
        "fresh_confirmation_candidate": confirmation_candidate,
        "forward_candidate": confirmation_candidate,
        "fresh_confirmation_required": True,
        "automatic_promotion": False,
        "selection_cohort_may_confirm_winner": False,
        "protocol": protocol,
    }


def evaluate_published_paper(
    rows: list[dict[str, Any]],
    *,
    cohort_id: str | None,
) -> dict[str, Any]:
    protocol = published_paper_protocol_definition()
    shape = evidence_shape(
        rows,
        value_field="net_realised_r",
        time_fields=("completed_at",),
    )
    lower = day_cluster_bootstrap_lower_bound(
        rows,
        value_field="net_realised_r",
        time_fields=("completed_at",),
        alpha=FAMILY_ALPHA,
        label=f"published_paper|{cohort_id or 'none'}",
    )
    gates = {
        "minimum_triggered": shape["triggered"] >= PUBLISHED_MIN_TRIGGERED,
        "minimum_independent_days": shape["independent_days"] >= PUBLISHED_MIN_INDEPENDENT_DAYS,
        "minimum_independent_weeks": shape["independent_weeks"] >= PUBLISHED_MIN_INDEPENDENT_WEEKS,
        "positive_net_expectancy": shape["net_expectancy_r"] is not None and shape["net_expectancy_r"] > 0.0,
        "single_day_concentration": shape["max_single_day_trigger_share"] <= PUBLISHED_MAX_SINGLE_DAY_TRIGGER_SHARE,
        "one_sided_lower_bound_positive": lower is not None and lower > 0.0,
    }
    supported = bool(all(gates.values()))
    if supported:
        grade = "FORWARD_NET_SUPPORTED"
    elif not gates["minimum_triggered"]:
        grade = "UNPROVEN"
    elif not gates["minimum_independent_days"] or not gates["minimum_independent_weeks"]:
        grade = "EVIDENCE_CLUSTERED"
    elif not gates["single_day_concentration"]:
        grade = "EVIDENCE_CONCENTRATED"
    elif not gates["positive_net_expectancy"]:
        grade = "NEGATIVE_OR_FLAT"
    else:
        grade = "UNCERTAIN"
    return {
        "protocol_version": PUBLISHED_PAPER_PROTOCOL_VERSION,
        "cohort_id": cohort_id,
        **shape,
        "one_sided_95pct_day_cluster_lower_bound_r": lower,
        "quality_gates": gates,
        "failed_quality_gates": [name for name, passed in gates.items() if not passed],
        "forward_net_supported": supported,
        "grade": grade,
        "support_label_consistent_with_all_quality_gates": (grade == "FORWARD_NET_SUPPORTED") == supported,
        "sample_count_alone_never_proves_edge": True,
        "automatic_money_approval": False,
        "protocol": protocol,
    }
