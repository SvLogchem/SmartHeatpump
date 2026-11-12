"""Default values and ranges for all user-adjustable settings (plain data)."""
from __future__ import annotations

# key, display name, min, max, step, unit, default, group
# group "core" is always created, group "dhw" only when a tank sensor is configured.
NUMBER_SPECS: list[tuple] = [
    # --- stooklijn (handmatige terugval, wordt gemengd met het geleerde model) ---
    ("basis_temperatuur", "Slimme WP Basis Temperatuur", 15.0, 35.0, 0.5, "°C", 22.0, "core"),
    ("setpoint_offset", "Slimme WP Setpoint Offset", -10.0, 10.0, 0.5, "°C", 0.0, "core"),
    ("stooklijn", "Slimme WP Stooklijn Helling", 0.1, 1.5, 0.05, "", 0.4, "core"),
    ("horizon", "Slimme WP Weersverwachting Horizon", 1.0, 12.0, 1.0, "h", 4.0, "core"),
    ("zon_factor", "Slimme WP Zon Compensatie Factor", 0.0, 5.0, 0.1, "", 2.0, "core"),
    # --- beveiliging / compressor ---
    ("bivalent_temp", "Slimme WP Bivalente Temperatuur", -10.0, 10.0, 0.5, "°C", -5.0, "core"),
    ("minimum_runtime", "Slimme WP Minimale Draaitijd", 5.0, 60.0, 5.0, "min", 15.0, "core"),
    ("minimum_stilstand", "Slimme WP Minimale Stilstandtijd", 1.0, 60.0, 1.0, "min", 10.0, "core"),
    ("waakhond_marge", "Slimme WP Waakhond Marge", 0.1, 2.0, 0.1, "°C", 0.5, "core"),
    ("min_freq", "Slimme WP Compressor Drempel", 1.0, 50.0, 1.0, "Hz", 2.0, "core"),
    ("max_flow_temp", "Slimme WP Max Aanvoertemperatuur", 25.0, 60.0, 1.0, "°C", 40.0, "core"),
    ("min_kamertemp", "Slimme WP Minimale Kamertemperatuur", 10.0, 20.0, 0.5, "°C", 16.0, "core"),
    ("stookgrens", "Slimme WP Zomermodus Stookgrens", 10.0, 25.0, 0.5, "°C", 18.0, "core"),
    # --- comfort & planning ---
    ("setpoint_dag", "Slimme WP Setpoint Dag", 15.0, 25.0, 0.1, "°C", 21.0, "core"),
    ("setpoint_nacht", "Slimme WP Setpoint Nacht", 15.0, 25.0, 0.1, "°C", 20.4, "core"),
    ("nacht_start", "Slimme WP Starttijd Nacht", 0.0, 23.0, 1.0, "h", 23.0, "core"),
    ("nacht_eind", "Slimme WP Eindtijd Nacht", 0.0, 23.0, 1.0, "h", 7.0, "core"),
    ("bedtijd", "Slimme WP Bedtijd (vloer warm)", 0.0, 24.0, 0.5, "h", 21.0, "core"),
    ("voorverwarm_max", "Slimme WP Max Voorverwarm Opslag", 0.0, 8.0, 0.5, "°C", 4.0, "core"),
    ("stille_boost_max", "Slimme WP Max Opslag Stille Uren", 0.0, 5.0, 0.5, "°C", 1.5, "core"),
    ("stille_voorkeur", "Slimme WP Voorkeur Stille Uren", 0.0, 3.0, 0.5, "", 1.0, "core"),
    ("tolerantie_laag", "Slimme WP Tolerantie Te Koud", 0.1, 1.5, 0.1, "°C", 0.3, "core"),
    ("tolerantie_hoog", "Slimme WP Tolerantie Te Warm", 0.1, 2.0, 0.1, "°C", 0.5, "core"),
    # --- stroomprijs & zonnepanelen ---
    ("max_stroomprijs", "Slimme WP Max Stroomprijs", 0.05, 3.0, 0.01, "€", 0.35, "core"),
    ("prijs_gevoeligheid", "Slimme WP Prijsgevoeligheid", 0.0, 3.0, 0.1, "", 1.0, "core"),
    ("pv_boost", "Slimme WP Zonnepanelen Boost", 0.0, 5.0, 0.5, "°C", 0.0, "core"),
    ("pv_drempel", "Slimme WP Zonnepanelen Drempel", 200.0, 8000.0, 100.0, "W", 1500.0, "core"),
    # --- warm tapwater (optioneel) ---
    ("dhw_min_temp", "Slimme WP Tapwater Minimum", 25.0, 60.0, 1.0, "°C", 40.0, "dhw"),
    ("dhw_doel_temp", "Slimme WP Tapwater Doel", 30.0, 65.0, 1.0, "°C", 50.0, "dhw"),
    ("dhw_legionella_temp", "Slimme WP Legionella Temperatuur", 55.0, 70.0, 1.0, "°C", 60.0, "dhw"),
    ("dhw_legionella_dagen", "Slimme WP Legionella Interval", 1.0, 30.0, 1.0, "d", 7.0, "dhw"),
    ("dhw_max_looptijd", "Slimme WP Tapwater Max Looptijd", 15.0, 240.0, 5.0, "min", 90.0, "dhw"),
]

# key, display name, default, icon, group
SWITCH_SPECS: list[tuple] = [
    ("regeling_actief", "Slimme Regeling Actief", True, "mdi:auto-fix", "core"),
    ("leren_actief", "Slimme WP Leren Actief", True, "mdi:brain", "core"),
    ("voorverwarmen_actief", "Slimme WP Voorverwarmen Actief", True, "mdi:radiator", "core"),
    ("prijssturing_actief", "Slimme WP Prijssturing Actief", True, "mdi:currency-eur", "core"),
    ("dhw_actief", "Slimme WP Tapwatersturing Actief", True, "mdi:water-boiler", "dhw"),
]

DEFAULTS: dict[str, float] = {s[0]: s[6] for s in NUMBER_SPECS}
SWITCH_DEFAULTS: dict[str, bool] = {s[0]: s[2] for s in SWITCH_SPECS}

# Entities from v1 that no longer exist; their registry entries are removed on upgrade.
REMOVED_NUMBER_KEYS = ("dag_start", "dag_eind")
