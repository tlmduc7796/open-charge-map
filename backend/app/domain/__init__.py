"""Core EV charging domain models, repositories, and calculations."""

from backend.app.domain.repositories import DomainData, load_domain_data

__all__ = ["DomainData", "load_domain_data"]
