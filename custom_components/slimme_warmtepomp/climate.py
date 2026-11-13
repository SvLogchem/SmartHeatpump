"""Climate platform: the thermostat of the self-learning controller."""
from __future__ import annotations

from homeassistant.components.climate import (
    ClimateEntity, ClimateEntityFeature, HVACAction, HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.helpers.restore_state import RestoreEntity

from .const import CONF_ROOM
from .engine.controller import PROGRAM_DAY, PROGRAM_MANUAL, PROGRAM_NIGHT
from .entity import SlimmeWPEntity

PRESET_DAY, PRESET_NIGHT, PRESET_MANUAL = PROGRAM_DAY, PROGRAM_NIGHT, PROGRAM_MANUAL


class SlimmeWarmtepompThermostaat(SlimmeWPEntity, ClimateEntity, RestoreEntity):
    # v1 behaviour: HEATING = compressor runs, FAN = "circuleren" (pump on, compressor stopped),
    # IDLE = "stand-by" (the controller switched the heat pump off), OFF = system off.
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_preset_modes = [PRESET_DAY, PRESET_NIGHT, PRESET_MANUAL]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
    )
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_translation_key = "slimme_wp_thermostaat"
    _attr_precision = 0.1
    _attr_target_temperature_step = 0.1
    _attr_min_temp = 15.0
    _attr_max_temp = 25.0

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "climate", "Slimme WP Thermostaat", "climate.slimme_wp_thermostaat")

    @property
    def available(self) -> bool:
        return True

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is None:
            return
        c = self.coordinator
        c.hvac_on = last.state != HVACMode.OFF
        if last.attributes.get("preset_mode") == PRESET_MANUAL:
            c.preset = PRESET_MANUAL
            try:
                c.manual_temp = float(last.attributes.get("temperature"))
            except (TypeError, ValueError):
                pass

    # --- state
    @property
    def hvac_mode(self) -> HVACMode:
        return HVACMode.HEAT if self.coordinator.hvac_on else HVACMode.OFF

    @property
    def preset_mode(self) -> str:
        if self.coordinator.preset == PRESET_MANUAL:
            return PRESET_MANUAL
        d = self.decision
        return d.program if d else PRESET_DAY

    @property
    def current_temperature(self) -> float | None:
        return self.coordinator._num(self.coordinator.cfg.get(CONF_ROOM))

    @property
    def target_temperature(self) -> float:
        if self.coordinator.preset == PRESET_MANUAL:
            return self.coordinator.manual_temp
        d = self.decision
        return d.room_setpoint if d else 21.0

    @property
    def hvac_action(self) -> HVACAction:
        d = self.decision
        if not self.coordinator.hvac_on:
            return HVACAction.OFF
        if d is not None and d.switch_state == "off":
            return HVACAction.IDLE
        if d is not None and d.heating:
            return HVACAction.HEATING
        return HVACAction.FAN

    @property
    def extra_state_attributes(self) -> dict:
        d = self.decision
        return {} if d is None else {"reden": d.reason, "programma": d.program}

    # --- commands
    async def async_set_temperature(self, **kwargs) -> None:
        if ATTR_TEMPERATURE in kwargs:
            self.coordinator.manual_temp = float(kwargs[ATTR_TEMPERATURE])
            self.coordinator.preset = PRESET_MANUAL
            self.async_write_ha_state()
            await self.coordinator.async_request_refresh()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """'Dag'/'Nacht' return to the automatic schedule; 'Handmatig' keeps the last manual value."""
        self.coordinator.preset = PRESET_MANUAL if preset_mode == PRESET_MANUAL else PRESET_DAY
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        self.coordinator.hvac_on = hvac_mode != HVACMode.OFF
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([SlimmeWarmtepompThermostaat(entry.runtime_data)])
