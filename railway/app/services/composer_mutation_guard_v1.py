from __future__ import annotations

import random
from typing import Any

from app.services import composer as core

GUARD_VERSION = "eve-composer-mutation-guard-v1"
MUTABLE_CONDITION_PARAMETER_TYPES = frozenset(
    {
        "alignment_abs_min",
        "return_3_abs_min",
        "impulse_1_vs_3",
        "close_location_extreme",
        "wick_body_ratio_min",
    }
)

_original_available_genes = core._available_genes
_original_mutate_rules = core.mutate_rules


def _condition_parameter_is_mutable(condition: dict[str, Any]) -> bool:
    return str(condition.get("type") or "") in MUTABLE_CONDITION_PARAMETER_TYPES


def _available_genes_v1(rules: dict[str, Any]) -> list[str]:
    """Expose condition_parameter only when a supported condition can be changed.

    Discovery can now feed the composer richer MTF/scientist conditions. Some of
    those conditions carry fields such as ``min`` or ``threshold`` for their own
    semantics but are not parameter types understood by the legacy composer.
    Treating any extra dictionary key as mutable caused production cycles to
    raise ``Condition has no mutable parameter``.
    """
    genes = list(_original_available_genes(rules))
    if "condition_parameter" not in genes:
        return genes
    conditions = list((rules.get("entry") or {}).get("conditions") or [])
    if not any(_condition_parameter_is_mutable(dict(item or {})) for item in conditions):
        genes.remove("condition_parameter")
    return genes


def _mutate_rules_v1(
    parent_rules: dict[str, Any],
    rng: random.Random,
    preferred_genes: list[str] | None = None,
    exploration_rate: float = 0.0,
) -> core.Mutation:
    """Choose a valid mutation gene and mutate only recognised condition params."""
    available = _available_genes_v1(parent_rules)
    if not available:
        raise ValueError("Strategy has no available mutation genes")

    preferred = [gene for gene in (preferred_genes or []) if gene in available]
    exploration = max(0.0, min(1.0, exploration_rate))
    if preferred and rng.random() >= exploration:
        gene = rng.choice(preferred)
    else:
        gene = rng.choice(available)

    if gene != "condition_parameter":
        # Force the already-validated gene through the original mutation engine.
        # The original helper still owns all existing mutation semantics.
        return _original_mutate_rules(
            parent_rules,
            rng,
            preferred_genes=[gene],
            exploration_rate=0.0,
        )

    rules = core._deepcopy(parent_rules)
    conditions = list((rules.get("entry") or {}).get("conditions") or [])
    mutable = [
        index
        for index, item in enumerate(conditions)
        if _condition_parameter_is_mutable(dict(item or {}))
    ]
    if not mutable:
        # This should be impossible because _available_genes_v1 removed the gene,
        # but fail explicitly rather than silently creating a no-op mutation.
        raise ValueError("No supported condition parameter is available to mutate")

    index = rng.choice(mutable)
    old_condition, new_condition = core._mutate_condition_parameter(conditions[index], rng)
    conditions[index] = new_condition
    rules["entry"]["conditions"] = conditions
    rules["engine_version"] = "eve-discovery-evolution-v3"
    return core.Mutation(
        gene="condition_parameter",
        old=old_condition,
        new=new_condition,
        rules=rules,
    )


core._available_genes = _available_genes_v1
core.mutate_rules = _mutate_rules_v1
