from app.services.mt5_evidence_gate import requires_parity_proof


def test_evidence_seed_requires_parity_before_mt5_export():
    frozen = {
        "rules": {
            "market": {
                "evidence_seed_version": "eve-evidence-hypothesis-seeder-v1",
                "mt5_export_gate": "advanced_rule_parity_required",
            }
        }
    }
    assert requires_parity_proof(frozen) is True


def test_explicit_parity_pass_releases_gate():
    frozen = {
        "rules": {
            "market": {
                "mt5_export_gate": "advanced_rule_parity_required",
                "advanced_rule_parity_passed": True,
            }
        }
    }
    assert requires_parity_proof(frozen) is False


def test_ordinary_survivor_is_not_blocked_by_evidence_gate():
    assert requires_parity_proof({"rules": {"market": {}}}) is False
