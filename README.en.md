<p align="center"><img src="icon.png" width="128" alt="Smart Heat Pump"></p>

# SmartHeatpump for Home Assistant

🇳🇱 **Nederlandse versie: [README.md](README.md)** (the Dutch README is the most detailed one; this page covers everything you need to get going).

A self-learning control for heat pumps with underfloor heating. Built for an Alsavo pump through Tuya Local, but usable with any pump whose target temperature you can set as a `number`.

Everything user-facing is available in English and Dutch: the setup wizard, repairs, notifications, services, the dashboard and the entity display names follow the language of Home Assistant (Dutch for `nl`, English for every other language). **Entity IDs never change** (`number.slimme_wp_setpoint_dag` stays that in every language), so automations and dashboards work the same.

## What it does

- **Learns your house.** From your sensors it learns how fast the house cools, how slowly the floor heats up and cools down and how much the sun contributes. A heating curve of its own follows from that. Until the model has enough data (about 2-3 days) your manual heating curve is used and gradually replaced.
- **Floor warm at bedtime.** The planner looks ahead (weather, sun, day/night setpoints) and pre-heats the floor *before* bedtime so the room does not drop below the setpoint afterwards and the pump does not have to recover hard at night. An evening correction learns: if the room was too cold one hour after bedtime, the floor is charged a bit further the next day.
- **Quiet hours.** From bedtime to the end of the night the maximum storage is limited and energy use weighs more.
- **Electricity price (optional).** With a price sensor that has a forecast (Nordpool, EPEX Spot, Frank Energie, ENTSO-E, …) heat is shifted to cheaper hours, within the comfort tolerance. The unit of the sensor is read and converted to currency per kWh, so a price in ct/kWh or EUR/MWh works too.
- **Solar panels (optional).** With a surplus, power counts for less and *Solar Panel Boost* can store extra heat in the floor.
- **Hot water (optional).** Tank temperature sensor plus a switch gives you a minimum temperature, charging on cheap/sunny hours, a legionella cycle and a maximum run time.
- **Compressor protection.** Minimum run and off time, no short cycling from rounding (setpoints are averaged over time), defrost detection, summer mode on the 24-hour average, frost protection and a minimum room temperature.
- **Frequency table.** It learns which compressor frequency belongs to which difference between setpoint and return water, from the pump's minimum to its maximum Hz, and uses it for soft running and for the frequency limit (day / quiet hours).
- **Defrost and ice monitoring.** Learns defrost cycles (with an optional coil sensor), predicts the next one and warns about ice formation.

## Installation

HACS → Custom repository → `https://github.com/SvLogchem/SmartHeatpump` → install → restart → Settings → Devices & services → Add integration → *Smart Heat Pump*.

Required: room and outdoor temperature. For learning you also need the **return temperature** (or a floor sensor) and the **supply temperature**; the compressor frequency makes it more accurate. Everything can be changed later via *Reconfigure*.

### Setup wizard

You do not fill in one huge form; the installation takes five short steps. *Reconfigure* starts the same wizard with your current choices.

1. **Installation:** control on return or supply temperature, step size, the **heat pump type** (*Alsavo/Tuya* or *General*, which starts more cautiously) and the **integration of the pump** (for example `localtuya`). The latter filters the pump fields and drives the suggestions; switch the filter off if your sensors come from several integrations.
2. **Room and outdoors:** main room, optional **extra rooms** (as many as you like), outdoor, supply, return and floor sensors.
3. **Heat pump:** frequency, power (or voltage and current), **as many flow rate sensors as you have**, coil and the pump's own outdoor sensor.
4. **Control:** the `number` for the target temperature and the on/off switch. Leave both empty to only measure and learn (shadow mode).
5. **Extras:** tick what you want to connect (weather and price, solar and grid, windows and doors, presence, hot water, notifications). Every ticked item adds one short screen; unticked items are skipped. Unticking something in *Reconfigure* removes its links.

Fields are pre-filled when a good candidate is found (by unit, device class and name: °C, Hz, W, l/min, …). It is a suggestion: please check it. Existing installations are converted automatically.

### Several rooms

All rooms share one water circuit, so heating per room is not possible. You can choose how the rooms count:

- **Main room steers, extra rooms guard** (default): control follows the main room. If an extra room gets colder than *Minimum Extra Rooms* (default 17 °C) an extra heat demand of the same size (at most 3 K) is added, so it heats longer until that room is back above its minimum. The learned house model, the evening correction and the heating-curve correction keep learning from the real temperature of the main room: a cold bedroom does not make the living room look "too cold" to the model.
- **Average** of all rooms.
- **Coldest:** the coldest room decides.

An extra room that drops out is ignored. If the **main sensor** drops out the control holds its last state (as for any missing room sensor, with frost protection still active): the other rooms do not take the living room's place, because the target is a target for the main room.

### Sensor check (Repairs)

The integration watches the sensors it uses and reports problems under *Settings → System → Repairs* (and as a notification if you set one up):

- a sensor without a value for 30 minutes;
- a sensor not updated for 6 hours (not for the compressor frequency, which may stay on one value for hours, and not for flow, return, floor and power while the pump stands still);
- an implausible value (for example 85 °C as room temperature) for more than 10 minutes;
- an outdoor temperature that differs 8 K or more from the pump's own outdoor sensor for 2 hours (sun on the sensor?).

The extra room sensors are checked too. A problem disappears by itself once the sensor is fine again.

### Notifications on your phone

Pick one or more `notify` services under *Extras → Notifications to your phone* (for example the Home Assistant app). You get a message for:

- frost protection that had to switch the pump on;
- ice formation (with the reason in plain language);
- **a room that stays too cold for too long** (*Room Too Cold Alert After*, default 3 hours, and *Room Too Cold Alert Margin*, default 1.5 °C below the target; not in summer mode or while defrosting; when away the away setpoint is the target);
- sensor problems (at most once a day per problem);
- the weekly report.

Messages follow the language of Home Assistant.

### Weekly report

Every Monday morning (from 08:00) you get a summary of the last 7 days: energy use, cost, COP, kWh per degree day, run time, defrost cycles and the share of time the room stayed inside the comfort band. It is in `sensor.slimme_wp_weekrapport` (state: kWh, text in the attribute `rapport`), on the dashboard under *Costs & analysis*, and sent as a notification when you picked a service. Switch sending off with `switch.slimme_wp_weekrapport_actief` (available once a notify service is chosen).

### Export and import

For a new installation, a backup, or to share your settings:

- `slimme_warmtepomp.exporteer` writes all settings, switches and (optionally) what the control has learned to `slimme_warmtepomp_export.json` in your config folder and also returns them as the response. You choose separately:
  - `pompkennis` (pump knowledge, on by default): the frequency table and defrost behaviour. That belongs to the pump and is useful for anyone with the same pump.
  - `huiskennis` (house knowledge, off by default): the house model (cooling time, floor), the evening correction, the heating curve and the statistics. That belongs to your house; in another house it would control wrongly for weeks until it is unlearned. Only switch it on for a backup of your own installation.
- `slimme_warmtepomp.importeer` reads that file (or the `data` you pass) and applies it, with the same two choices. Values are kept within the allowed limits; anything that could not be applied is listed in the response. Whatever is not in the export is left alone: an export with only pump knowledge leaves your own house model as it is.

The actions `reset_model`, `exporteer` and `importeer` can only be called by administrators (and by automations and scripts without a user). A user without admin rights, for example on a shared tablet, cannot wipe the learned model.

Your sensor links are deliberately not included: they belong to your installation.

## Recommended settings for "floor warm at 21:00"

| Setting | Value |
|---|---|
| Bedtime | 21:00 |
| Setpoint Day / Night | e.g. 21.0 / 20.4 (night from 23:00) |
| Tolerance Too Cold | 0.2-0.3 °C (lower = stricter, but more expensive) |
| Quiet Hours Preference | 1-2 |
| Max Storage Quiet Hours | 1.5 °C |

After a few days check *Model Confidence*, *Predicted Room 1h After Bedtime* and *Evening Correction*, and the attributes of *Calculated Setpoint* (such as `plan_reden` and the learned time constants).

## Optional features

Everything below is optional: if you do not link the sensor the matching entities do not exist.

- **Window/door open:** after `raam_vertraging` minutes (default 5) heating stops; the model does not learn while a window is open. In real need (room below the minimum) it heats anyway.
- **Presence / holiday:** when everybody is away longer than `afwezig_vertraging` the away setpoint applies. With a return time (input_datetime) the planner pre-heats in time; a manual choice always wins.
- **Grid import limit:** if import stays above the limit for 5 minutes the pump is temporarily not loaded further (max. 45 min, then a 15 min pause).
- **COP and starts per day**, **costs and degree days** (per day, week, month and year, no helpers or YAML needed), and **smart control on versus off** (kWh per degree day compared over 28 days; switch *Smart Control Active* off for a week to compare).
- **Shortfall boost:** if the room stays too cold longer than the wait time, the setpoint is raised so the compressor runs at the boost frequency; with a floor sensor and learned model the boost stops when the floor holds enough heat.
- **Frost protection:** below the outdoor limit (default 3 °C) or when the return stays under 8 °C the pump is kept on at the lowest setpoint. The pump is never switched off around a defrost cycle.
- **Partial relearning:** *Relearn Percentage* and the *Start Relearning* button forget a part of the model; the service `slimme_warmtepomp.reset_model` wipes it entirely.

## Pump profile (another heat pump?)

The control is not tied to one brand. The properties of your pump are settings (category *Configuration*) that you rarely need to touch:

| Setting | Default | What it does |
|---|---|---|
| Pump Minimum Frequency | 0 = learn | Lowest compressor frequency. Limits the frequency table downwards. |
| Pump Maximum Frequency | 0 = learn | Highest frequency. The table stops once it is reached. |
| Pump Start Difference | 2.8 K | How far the setpoint must be above the water temperature to start the compressor (Alsavo/Midea: about 2.5 K). |
| Pump Stop Difference | 3.0 K | How far the setpoint must be below the water temperature to stop it. |
| Pump Minimum Power When Running | 250 W | Only used without a frequency sensor. |
| Glycol Percentage | 0 % | Corrects the thermal power (and COP) for glycol: about 0.3 % less per % glycol. |

The *General* profile in the wizard starts with more cautious values (start/stop difference 3.5 K, minimum power 100 W) and learns from there.

**Heating curve.** Three layers: (1) *Base Temperature*, *Setpoint Offset* and *Heating Curve Slope*, the manual curve the control falls back on while learning; (2) *Heating Curve Correction At -5 / 5 / 15 °C*, three corrections in degrees across the whole curve; (3) the automatic correction per outdoor temperature the integration maintains itself. *Lowest Heat Pump Setpoint* and *Max Supply Temperature* limit the result.

## Ready-made dashboard

The integration ships a complete dashboard. Nothing to copy: it is built from the entities your installation actually has, so it adapts to your sensors and optional parts and grows with every update. It is shown in English when Home Assistant is not set to Dutch.

1. Restart Home Assistant after installing or updating.
2. *Settings → Dashboards → Add dashboard → Community dashboards → Smart Heat Pump* (needs Home Assistant 2026.5 or newer).
3. To use it in an existing dashboard, open the raw configuration and add:

```yaml
strategy:
  type: custom:slimme-warmtepomp
```

Tabs: **Overview** (status, switches, what the control is doing, rooms, performance, trend), **Learning** (model confidence and the learned tables), **Settings** (every setting, grouped), **Heat pump** (your own sensors incl. every flow sensor, and charts) and **Costs & analysis** (incl. the weekly report). Charts use *mini-graph-card* when you have it (HACS), otherwise the built-in history graph; the history graph *Control on/off (30 days)* shows at most what the recorder keeps (10 days by default; set `purge_keep_days: 30` under `recorder:` for all 30). If it does not show up in the list, add `/slimme_warmtepomp_frontend/slimme-warmtepomp-strategy.js` as a JavaScript module resource.

## Entities

- `climate.slimme_wp_thermostaat`: day/night follows the schedule. A manual setting stays until the next day/night change.
- `sensor.slimme_wp_setpoint`: the last written water temperature, with a lot of diagnostics in the attributes.
- Other sensors: reason of the last decision, plan, model confidence, learned cooling times, estimated floor temperature, thermal/electrical energy (kWh, fit for the energy dashboard), average COP, costs, weekly report.
- Switches to turn parts off: *Smart Control Active*, *Learning*, *Pre-heating*, *Price Control*, *Hot Water Control*, and more.
- **Shadow mode:** with *Smart Control Active* off everything is still calculated and shown, but nothing is sent to the pump or the switch.
- Services: `reset_model`, `exporteer` (export) and `importeer` (import).

## Limitations

- The model is a two-node model (floor + room) with the return or floor temperature as floor proxy. With a very heavy screed and cold evenings it can overshoot; lower *Tolerance Too Warm* or use a real floor sensor.
- Price forecasts are recognised from the shape of the attributes; check the attributes of *Calculated Setpoint* to see whether a forecast is used.
- Tested with a simulated house and a simulated Home Assistant environment (see `tests/`); the setup wizard, repairs and dashboard have not been run in a real installation yet. Please report anything odd.

## Changelog (v2.18.3)

- `sensor.slimme_wp_cop_gisteren` and `sensor.slimme_wp_starts_gisteren` now have `state_class: measurement`, and there is a new sensor `sensor.slimme_wp_kwh_per_graaddag_gisteren` (the final value of yesterday, empty after a day too mild to tell). Home Assistant therefore keeps statistics of them. The running values of today change all day, so their daily maximum came out too high; each bar of a statistics graph on the "yesterday" sensors is one day behind. A new sensor builds statistics from now on.
- The generated dashboard uses those sensors for *COP per day* and *kWh per degree day per day* (30 days).
- In the dashboard the status is called *Frost protection running* (the switch stays *active*). *Reason* and *Plan* only appear in the header now; the header badges *Water setpoint* and *COP today* and the badges at *Control* are gone (they were on the same page already). The header shows "–" instead of "None °C" while the thermostat is unavailable.
- New in the dashboard: tiles *Bivalent* and *Hot water*, *Degree days week*, a *Hot water* block on the *Heat pump* page (mode, cycle running, wait after a time-out and the last time-out) and a message in the rooms card when the main sensor is missing. Heating-curve corrections are shown in K. *Start relearning* is a button that asks for confirmation.
- Deliberately unchanged: `state_class` of the day, week and month counters stays `measurement`. With `total` Home Assistant no longer keeps a maximum, which the *Costs per day* graph uses.

## Changelog (v2.18.2)

- Hot water: a run that does not reach its target (for example legionella at 60 °C with a tank that reaches 55 °C) started again at once and kept the pump on hot water all day, with no space heating. After the maximum run time there is now a wait (24 hours for legionella, 6 hours for normal heating) and a notification; the house is heated in the meantime. The wait survives a restart (attribute `tapwater_wacht_tot`).
- Without a price sensor the legionella cycle starts in the afternoon (12:00 to 17:00) instead of straight away, also at night. With a cheap hour or a solar surplus it can still start earlier, and a day overdue it always starts.
- A cold guard room no longer feeds the stored integrator or the heating-curve learning either; they only see the real main room. The shortfall counts only as extra heat demand.
- Electricity price: the unit of the sensor is read and converted to currency per kWh (ct/kWh, EUR/MWh). If the unit differs from before, the stored price history starts again.
- `reset_model`, `exporteer` and `importeer` are for administrators only (automations and scripts without a user are fine).
- Flat price lists (`today`/`tomorrow`) stay hourly on the days the clock changes (23, 24 or 25 slots), not at 00:57 and 01:55.
- The frost return-water check clears its start time when the water is back above the limit, so the 5 minutes must really be in a row.
- *Learned Heating Curve Correction* and *Floor Heat Shortfall* use unit K instead of °C (they are differences). *Max Electricity Price* has unit €/kWh.
- No more `turn_on` to the hot-water switch every 2 minutes; only if it is not on yet.
- The generated dashboard assumes the default entity IDs (`sensor.slimme_wp_setpoint`, `climate.slimme_wp_thermostaat`, ...): if you rename one, its card disappears silently.
- Still open: `state_class` of the day, week and month counters, the 142 entities none of which is disabled by default, the sensor-type filter in the wizard, the first control cycle after the platforms load, "Night" in the thermostat and the unit of *Expected Sun Reduction*. Those touch existing statistics or the design and I would like to agree on them first.

## Changelog (v2.18.1)

- Shadow mode (*Control Active* off) is now also respected when the room sensor drops out during frost; before, the integration still switched the pump on.
- If the main living-room sensor drops out the control holds its last state instead of steering on the average of the extra rooms.
- A guard room that is too cold counts as extra heat demand and no longer as a "too cold living room" for the learned model, the evening correction, the heating-curve correction and the prediction.
- No more false "sensor not updated" for the compressor frequency, nor for the pump sensors while the pump stands still. The extra room sensors are part of the sensor check and the number in the implausible-value message is rounded.
- The status *Smart HP Frost Protection Running* and the switch *Smart HP Frost Protection Active* no longer share a name (entity IDs unchanged).
- Export and import: *pump knowledge* and *house knowledge* are chosen separately; the house model is no longer included by default.
- *Next defrost cycle* counts compressor run time (no more "199 minutes overdue" after a long standstill) and the defrost interval is learned in run time too.
- When a message was last sent is remembered, so a restart during frost or a sensor problem does not send it again.
- No "living room too cold" message while a window or door is open.
- `async_migrate_entry` refuses a configuration saved by a newer version.
- The release now also waits for hassfest and the HACS check.
- Left as it is on purpose: the preset names *Dag*, *Nacht* and *Handmatig* stay Dutch (also for English users). Hassfest only accepts lowercase translation keys; other names would break automations that use these presets.

## License

MIT, see [LICENSE](LICENSE).

## Tests

```
pip install pytest
pytest              # about 2-3 minutes; the simulation runs weeks of control time
```
