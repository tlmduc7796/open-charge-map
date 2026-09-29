"""Load and validate the explicit, team-reviewed multi-domain ML schema."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_SCHEMA_PATH = ROOT_DIR / "ml" / "config" / "domain_schema.draft.json"


@dataclass(frozen=True)
class ModelProfile:
    name: str
    enabled: bool
    sequence_features: tuple[str, ...]
    context_features: tuple[str, ...]
    serving_status: str


@dataclass(frozen=True)
class DomainSchema:
    path: Path
    deployment_region: str
    target_name: str
    profiles: dict[str, ModelProfile]
    raw: dict[str, Any]

    def profile(self, name: str) -> ModelProfile:
        try:
            return self.profiles[name]
        except KeyError as exc:
            raise ValueError(f"Unknown model profile: {name}") from exc

    def training_requirements(self, name: str) -> dict[str, object]:
        profile = self.profile(name)
        selected = set((*profile.sequence_features, *profile.context_features))
        domains = {
            domain_name: config.get("status")
            for domain_name, config in self.raw["domains"].items()
            if selected.intersection(config.get("features", ()))
        }
        return {
            "profile": name,
            "enabled": profile.enabled,
            "deployment_region": self.deployment_region,
            "target": self.target_name,
            "sequence_features": profile.sequence_features,
            "context_features": profile.context_features,
            "required_domain_status": domains,
        }


def load_domain_schema(path: Path = DEFAULT_SCHEMA_PATH) -> DomainSchema:
    if not path.is_file():
        raise FileNotFoundError(f"ML domain schema does not exist: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    required = {"deployment_region", "target", "domains", "model_profiles", "handoff_checklist"}
    missing = required - set(raw)
    if missing:
        raise ValueError(f"ML domain schema misses keys: {sorted(missing)}")
    profiles: dict[str, ModelProfile] = {}
    declared_features = {
        feature for domain in raw["domains"].values() for feature in domain.get("features", [])
    }
    for name, config in raw["model_profiles"].items():
        sequence = tuple(config.get("sequence_features", ()))
        context = tuple(config.get("context_features", ()))
        unknown = set((*sequence, *context)) - declared_features
        if unknown:
            raise ValueError(f"Profile {name} has undeclared features: {sorted(unknown)}")
        profiles[name] = ModelProfile(
            name=name,
            enabled=bool(config.get("enabled")),
            sequence_features=sequence,
            context_features=context,
            serving_status=str(config.get("serving_status", "unknown")),
        )
    return DomainSchema(
        path=path,
        deployment_region=str(raw["deployment_region"]),
        target_name=str(raw["target"]["name"]),
        profiles=profiles,
        raw=raw,
    )
