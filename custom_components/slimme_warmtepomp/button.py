"""Button platform: relearn part of the model on demand."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory

from .entity import SlimmeWPEntity


class RelearnButton(SlimmeWPEntity, ButtonEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:restart-alert"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "opnieuw_aanleren", "Slimme WP Opnieuw Aanleren Starten",
                         "button.slimme_wp_opnieuw_aanleren")

    @property
    def available(self) -> bool:
        return True

    async def async_press(self) -> None:
        await self.coordinator.async_reset_model(self.coordinator.settings["herleer_percentage"])


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([RelearnButton(entry.runtime_data)])
