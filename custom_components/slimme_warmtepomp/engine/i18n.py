"""Texts the integration writes itself (notifications, reports): Dutch for Dutch Home Assistants, English otherwise."""
from __future__ import annotations


def lang(code) -> str:
    return "nl" if str(code or "").lower().startswith("nl") else "en"


MESSAGES: dict[str, dict[str, str]] = {
    "nl": {
        "frost_title": "Warmtepomp: vorstbeveiliging",
        "frost_water": "het water in de pomp is te koud",
        "frost_outside": "het buiten onder de vorstgrens is",
        "frost_body": "De vorstbeveiliging heeft de warmtepomp ingeschakeld omdat {why}. "
                      "De pomp blijft draaien op het laagste setpoint zolang er vorstgevaar is.",
        "ice_title": "Warmtepomp: mogelijk ijsvorming",
        "ice_body": "De slimme regeling vermoedt dat de warmtepomp ijs ophoopt: {reasons}. Controleer de ontdooi-instellingen "
                    "van de pomp (interval, starttemperatuur, maximale ontdooitijd) en kijk of de verdamper vrij is van ijs.",
        "ice_cop_zakt": "de COP zakt ver onder het niveau direct na het ontdooien",
        "ice_herstelt_niet": "de COP na het ontdooien wordt steeds slechter (ontdooien lost het ijs niet op)",
        "ice_vaker": "de pomp ontdooit steeds vaker",
        "ice_ontdooit_te_laat": "de pomp ontdooit niet terwijl het koud is en hij al lang draait",
        "ice_pomp_sensor_koud": "de buitensensor van de pomp is veel kouder dan de buitentemperatuur",
        "ice_ontdooi_zwak": "de ontdooicycli smelten het ijs niet weg (de coil wordt nauwelijks warm)",
        "ice_coil_koud": "de coil is vlak voor het ontdooien extreem koud (veel ijs)",
        "ice_kritiek": "de COP is langdurig rond 1",
        "cold_title": "Woonkamer te koud",
        "cold_body": "De kamer is al {hours:.0f} uur kouder dan gewenst ({room:.1f} °C, doel {target:.1f} °C). "
                     "Reden van de regeling: {reason}.",
        "health_title": "Warmtepomp: sensorprobleem",
        "health_body": "{problem}",
        "health_unavailable": "{entity} geeft al geruime tijd geen waarde ({role}).",
        "health_stale": "{entity} is al {hours:.0f} uur niet bijgewerkt ({role}).",
        "health_implausible": "{entity} meldt een onwaarschijnlijke waarde ({value}) voor {role}.",
        "health_outside": "De buitentemperatuur van je regeling ({a:.1f} °C) wijkt {diff:.0f} °C af van de buitensensor van de pomp ({b:.1f} °C). "
                          "Controleer welke sensor klopt.",
        "week_title": "Weekrapport warmtepomp",
        "week_body": "Afgelopen {days} dagen: {kwh:.1f} kWh verbruikt (€ {cost:.2f}), COP {cop}, {kwh_dd} kWh per graaddag, "
                     "kamer {comfort} van de tijd binnen de comfortband, {starts} ontdooicycli, draaitijd {run_h:.1f} uur.",
        "unknown": "onbekend",
    },
    "en": {
        "frost_title": "Heat pump: frost protection",
        "frost_water": "the water in the pump is too cold",
        "frost_outside": "it is below the frost limit outside",
        "frost_body": "Frost protection switched the heat pump on because {why}. "
                      "The pump keeps running at the lowest setpoint while there is a risk of frost.",
        "ice_title": "Heat pump: possible icing",
        "ice_body": "The smart control suspects the heat pump is icing up: {reasons}. Check the defrost settings of the pump "
                    "(interval, start temperature, maximum defrost time) and check that the evaporator is free of ice.",
        "ice_cop_zakt": "the COP drops far below its level right after defrosting",
        "ice_herstelt_niet": "the COP after defrosting keeps getting worse (defrosting does not remove the ice)",
        "ice_vaker": "the pump defrosts more and more often",
        "ice_ontdooit_te_laat": "the pump does not defrost although it is cold and has been running for a long time",
        "ice_pomp_sensor_koud": "the pump's own outdoor sensor is much colder than the outdoor temperature",
        "ice_ontdooi_zwak": "the defrost cycles do not melt the ice (the coil hardly warms up)",
        "ice_coil_koud": "the coil is extremely cold just before defrosting (a lot of ice)",
        "ice_kritiek": "the COP has been around 1 for a long time",
        "cold_title": "Living room too cold",
        "cold_body": "The room has been colder than wanted for {hours:.0f} hours ({room:.1f} °C, target {target:.1f} °C). "
                     "Reason given by the control: {reason}.",
        "health_title": "Heat pump: sensor problem",
        "health_body": "{problem}",
        "health_unavailable": "{entity} has not given a value for some time ({role}).",
        "health_stale": "{entity} has not been updated for {hours:.0f} hours ({role}).",
        "health_implausible": "{entity} reports an implausible value ({value}) for {role}.",
        "health_outside": "The outdoor temperature of your control ({a:.1f} °C) differs {diff:.0f} °C from the pump's own outdoor sensor ({b:.1f} °C). "
                          "Check which sensor is right.",
        "week_title": "Heat pump weekly report",
        "week_body": "Last {days} days: {kwh:.1f} kWh used (€ {cost:.2f}), COP {cop}, {kwh_dd} kWh per degree day, "
                     "room within the comfort band {comfort} of the time, {starts} defrost cycles, run time {run_h:.1f} hours.",
        "unknown": "unknown",
    },
}

ROLES = {
    "nl": {"kamer": "kamertemperatuur", "buiten": "buitentemperatuur", "aanvoer": "aanvoertemperatuur",
           "retour": "retourtemperatuur", "vloer": "vloertemperatuur", "frequentie": "compressorfrequentie",
           "vermogen": "vermogen", "pomp_setpoint": "setpoint van de pomp", "pomp_schakelaar": "schakelaar van de pomp"},
    "en": {"kamer": "room temperature", "buiten": "outdoor temperature", "aanvoer": "flow temperature",
           "retour": "return temperature", "vloer": "floor temperature", "frequentie": "compressor frequency",
           "vermogen": "power", "pomp_setpoint": "pump setpoint", "pomp_schakelaar": "pump switch"},
}


def msg(code, key: str, **kw) -> str:
    text = MESSAGES[lang(code)][key]
    return text.format(**kw) if kw else text


def role_name(code, role: str) -> str:
    return ROLES[lang(code)].get(role, role)
