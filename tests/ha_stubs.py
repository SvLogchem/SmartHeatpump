"""Minimal stand-ins for the parts of Home Assistant the integration imports.

They only exist so that the glue code (coordinator, entities, config flow) can
be imported and exercised without a real Home Assistant installation. This is
a smoke test for typos and wrong calls in *our* code, not a replacement for
testing inside Home Assistant.
"""
import enum
import sys
import types
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


class Dummy:
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__()

    def __class_getitem__(cls, item):
        return cls

    def __init__(self, *a, **k):
        pass


def D(name):
    return type(name, (Dummy,), {})


def mod(name, **attrs):
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    m.__getattr__ = lambda attr: type(attr, (Dummy,), {})  # unknown names become dummy classes
    sys.modules[name] = m
    parts = name.split(".")
    if len(parts) > 1:
        setattr(sys.modules[".".join(parts[:-1])], parts[-1], m)
    return m


class StrEnum(str, enum.Enum):
    pass


def install():
    if "homeassistant" in sys.modules and getattr(sys.modules["homeassistant"], "_stub", False):
        return
    ha = mod("homeassistant", _stub=True)
    mod("homeassistant.helpers")
    mod("homeassistant.components")
    mod("homeassistant.util")

    class HomeAssistantError(Exception):
        pass

    class UpdateFailed(Exception):
        pass

    class DataUpdateCoordinator(Dummy):
        def __init__(self, hass, logger, *, name=None, config_entry=None, update_interval=None):
            self.hass, self.config_entry, self.update_interval, self.data = hass, config_entry, update_interval, None
            self.last_update_success = True

        async def async_config_entry_first_refresh(self):
            self.data = await self._async_update_data()

        async def async_request_refresh(self):
            self.data = await self._async_update_data()

    class CoordinatorEntity(Dummy):
        def __init__(self, coordinator):
            self.coordinator = coordinator

        def async_write_ha_state(self):
            pass

        async def async_added_to_hass(self):
            pass

    class RestoreEntity(Dummy):
        async def async_get_last_state(self):
            return None

        async def async_added_to_hass(self):
            pass

    class Store:
        saved = {}

        def __init__(self, hass, version, key):
            self.key = key

        async def async_load(self):
            return Store.saved.get(self.key)

        async def async_save(self, data):
            Store.saved[self.key] = data

    TZ = ZoneInfo("Europe/Amsterdam")
    mod("homeassistant.util.dt",
        now=lambda: datetime.now(TZ), utcnow=lambda: datetime.now(timezone.utc),
        as_local=lambda d: d.astimezone(TZ),
        parse_datetime=lambda s: datetime.fromisoformat(s) if s else None)
    mod("homeassistant.exceptions", HomeAssistantError=HomeAssistantError)
    mod("homeassistant.core", State=Dummy, HomeAssistant=Dummy, ServiceCall=Dummy)
    mod("homeassistant.config_entries", ConfigEntry=Dummy, ConfigFlow=Dummy, ConfigFlowResult=dict)
    mod("homeassistant.helpers.storage", Store=Store)
    mod("homeassistant.helpers.update_coordinator", DataUpdateCoordinator=DataUpdateCoordinator,
        CoordinatorEntity=CoordinatorEntity, UpdateFailed=UpdateFailed)
    mod("homeassistant.helpers.restore_state", RestoreEntity=RestoreEntity)
    mod("homeassistant.helpers.device_registry", DeviceInfo=dict)
    class FakeRegistry:
        def __init__(self):
            self.existing, self.removed = {}, []

        def async_get_entity_id(self, domain, platform, unique_id):
            return self.existing.get((domain, platform, unique_id))

        def async_remove(self, entity_id):
            self.removed.append(entity_id)

    registry = FakeRegistry()
    mod("homeassistant.helpers.entity_registry", async_get=lambda hass: registry, REGISTRY=registry)
    mod("homeassistant.helpers.selector", SelectSelectorMode=StrEnum("SSM", {"DROPDOWN": "dropdown"}))
    ha.helpers.entity_registry = sys.modules["homeassistant.helpers.entity_registry"]
    ha.helpers.selector = sys.modules["homeassistant.helpers.selector"]
    consts = dict(
        ATTR_TEMPERATURE="temperature", PERCENTAGE="%",
        EntityCategory=StrEnum("EntityCategory", {"CONFIG": "config", "DIAGNOSTIC": "diagnostic"}),
        UnitOfTemperature=StrEnum("UnitOfTemperature", {"CELSIUS": "°C"}),
        UnitOfPower=StrEnum("UnitOfPower", {"WATT": "W", "KILO_WATT": "kW"}),
        UnitOfEnergy=StrEnum("UnitOfEnergy", {"KILO_WATT_HOUR": "kWh"}),
        UnitOfTime=StrEnum("UnitOfTime", {"HOURS": "h"}),
    )
    mod("homeassistant.const", **consts)
    mod("homeassistant.components.climate",
        ClimateEntity=D('ClimateEntity'),
        ClimateEntityFeature=enum.IntFlag("F", {"TARGET_TEMPERATURE": 1, "PRESET_MODE": 2, "TURN_ON": 4, "TURN_OFF": 8}),
        HVACMode=StrEnum("HVACMode", {"HEAT": "heat", "OFF": "off"}),
        HVACAction=StrEnum("HVACAction", {"HEATING": "heating", "IDLE": "idle", "OFF": "off"}))
    mod("homeassistant.components.number", NumberEntity=D('NumberEntity'),
        NumberMode=StrEnum("NumberMode", {"BOX": "box"}))
    mod("homeassistant.components.switch", SwitchEntity=D('SwitchEntity'))
    mod("homeassistant.components.sensor", SensorEntity=D('SensorEntity'),
        SensorDeviceClass=StrEnum("SDC", {"TEMPERATURE": "t", "POWER": "p", "ENERGY": "e"}),
        SensorStateClass=StrEnum("SSC", {"MEASUREMENT": "m", "TOTAL_INCREASING": "ti"}))
    mod("homeassistant.components.binary_sensor", BinarySensorEntity=D('SensorEntity'),
        BinarySensorDeviceClass=StrEnum("BDC", {"HEAT": "h", "PROBLEM": "p"}))
    if "voluptuous" not in sys.modules:
        try:
            import voluptuous  # noqa: F401
        except ImportError:
            class Marker:
                def __init__(self, key, **kw):
                    self.key = key
                def __hash__(self):
                    return hash(self.key)
                def __eq__(self, o):
                    return getattr(o, "key", o) == self.key
            mod("voluptuous", Schema=lambda d: d, Required=Marker, Optional=Marker)
