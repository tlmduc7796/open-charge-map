from __future__ import annotations

from ml.src.domain_schema import load_domain_schema


def test_draft_schema_exposes_candidate_domains_without_enabling_deep_learning():
    schema = load_domain_schema()

    transformer = schema.training_requirements("transformer")

    assert schema.deployment_region == "UNRESOLVED"
    assert transformer["enabled"] is False
    assert transformer["required_domain_status"]["weather"] == "candidate"
    assert transformer["required_domain_status"]["traffic"] == "candidate"
