"""Diagnostics: download the learned model, settings and last decision from the integration page."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data

REDACT = {"latitude", "longitude", "lat", "lon"}


async def async_get_config_entry_diagnostics(hass, entry) -> dict[str, Any]:
    coordinator = entry.runtime_data
    d = coordinator.data
    return async_redact_data({
        "config": dict(entry.data) | dict(entry.options),
        "settings": dict(coordinator.settings),
        "switches": dict(coordinator.switches),
        "learned_state": coordinator.controller.export_state(),
        "last_decision": None if d is None else {"reason": d.reason, "setpoint": d.setpoint,
                                                  "setpoint_raw": d.setpoint_raw, "diag": d.diag},
    }, REDACT)
