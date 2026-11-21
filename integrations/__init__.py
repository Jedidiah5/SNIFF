"""Optional, dormant integrations. Never imported by the sanctions engine.

Removing this package must not affect screening, harness, or console behaviour.
"""

from .registry import integration_status

__all__ = ["integration_status"]
