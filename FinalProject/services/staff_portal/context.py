"""Process-wide portal objects shared by the route handlers (``app.state.portal``)."""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from fastapi import Request

from staff_portal.auth import LoginThrottle
from staff_portal.catalog import Catalog
from staff_portal.config import PortalSettings
from staff_portal.scoring_client import ScoringClient
from staff_portal.simulator import SimulationManager
from staff_portal.store import PortalStore


@dataclass
class PortalContext:
    """Long-lived collaborators built once by :func:`staff_portal.app.create_app`."""

    settings: PortalSettings
    store: PortalStore
    scoring: ScoringClient
    catalog: Catalog
    simulator: SimulationManager
    throttle: LoginThrottle
    http: httpx.Client


def get_portal(request: Request) -> PortalContext:
    """Dependency returning the shared :class:`PortalContext`."""
    portal: PortalContext = request.app.state.portal
    return portal
