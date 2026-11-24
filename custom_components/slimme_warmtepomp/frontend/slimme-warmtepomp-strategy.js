/*
 * Slimme Warmtepomp - dashboard strategy
 *
 * Bouwt het complete dashboard uit de entiteiten die de integratie echt heeft aangemaakt, zodat het voor
 * iedere warmtepomp en iedere combinatie van optionele sensoren werkt en bij een update vanzelf meegroeit.
 *
 * Gebruik: Instellingen > Dashboards > Dashboard toevoegen > Slimme Warmtepomp, of in de raw-configuratie
 * van een dashboard:
 *     strategy:
 *       type: custom:slimme-warmtepomp
 *
 * Alleen standaard Home Assistant-kaarten, behalve de grafieken: staat "mini-graph-card" (HACS) geïnstalleerd
 * dan wordt die gebruikt, anders de ingebouwde history-graph.
 */
(() => {
  const root = typeof window !== "undefined" ? window : globalThis;
  const P = "slimme_wp_";
  const S = "sensor.slimme_wp_setpoint";
  const CLIMATE = "climate.slimme_wp_thermostaat";

  // ------------------------------------------------------------------ helpers
  const ex = (hass, id) => !!id && Object.prototype.hasOwnProperty.call(hass.states, id);
  const cards = (list) => list.filter(Boolean);

  const tile = (hass, entity, name, icon, color, cols, vertical) => {
    if (!ex(hass, entity)) return null;
    const c = { type: "tile", entity, name };
    if (icon) c.icon = icon;
    if (color) c.color = color;
    if (cols) c.grid_options = { columns: cols };
    if (vertical) c.vertical = true;
    return c;
  };
  const heading = (text, icon, badges) => {
    const c = { type: "heading", heading: text };
    if (icon) c.icon = icon;
    if (badges && badges.length) c.badges = badges;
    return c;
  };
  const badge = (hass, entity, name, icon, color) => {
    if (!ex(hass, entity)) return null;
    const b = { type: "entity", entity, name, show_name: true, show_state: true, show_icon: true };
    if (icon) b.icon = icon;
    if (color) b.color = color;
    return b;
  };
  const markdown = (title, content, columns) => {
    const c = { type: "markdown", content };
    if (title) c.title = title;
    if (columns) c.grid_options = { columns };
    return c;
  };
  const grid = (list, extra) => {
    const c = cards(list);
    return c.length > 1 || (c.length === 1 && c[0].type !== "heading") ? { type: "grid", cards: c, ...(extra || {}) } : null;
  };
  const rows = (hass, list) =>
    cards(list.map(([entity, name, icon]) => (ex(hass, entity) ? { entity, name, ...(icon ? { icon } : {}) } : null)));
  const entitiesCard = (hass, list, title) => {
    const r = rows(hass, list);
    return r.length ? { type: "entities", show_header_toggle: false, ...(title ? { title } : {}), entities: r } : null;
  };

  // Een grafiek: mini-graph-card als die er is, anders de ingebouwde history-graph.
  const graph = (hass, o) => {
    const ents = o.entities.filter((e) => ex(hass, e.entity));
    if (!ents.length) return null;
    const cols = o.columns || "full";
    const mini = root.customElements && root.customElements.get && root.customElements.get("mini-graph-card");
    if (mini && !o.noMini) {
      return {
        type: "custom:mini-graph-card", name: o.name, icon: o.icon, hours_to_show: o.hours,
        points_per_hour: o.pph || 4, line_width: 2, font_size: 75, grid_options: { columns: cols },
        entities: ents.map((e) => ({
          entity: e.entity, name: e.name, ...(e.color ? { color: e.color } : {}),
          ...(e.attribute ? { attribute: e.attribute } : {}), ...(e.y2 ? { y_axis: "secondary" } : {}),
        })),
        show: { legend: true, fill: o.fill || false, points: !!o.points },
        ...(o.bar ? { show: { graph: "bar", legend: false, points: false }, group_by: "date", aggregate_func: "max" } : {}),
      };
    }
    return {
      type: "history-graph", title: o.name, hours_to_show: o.hours, grid_options: { columns: cols },
      entities: ents.map((e) => ({ entity: e.entity, name: e.name })),
    };
  };
  const stats = (hass, entity, title, period, stat, chart, days) =>
    ex(hass, entity)
      ? { type: "statistics-graph", title, entities: [entity], period, stat_types: [stat], chart_type: chart,
          days_to_show: days, hide_legend: true, grid_options: { columns: "full" } }
      : null;

  const inputs = (hass) => (hass.states[S] && hass.states[S].attributes && hass.states[S].attributes.invoer_sensoren) || {};
  const n = (key) => `number.${P}${key}`;

  // ------------------------------------------------------------------ instellingen
  // [groep, icoon, [[sleutel, naam, icoon], ...]] - elke instelling van de integratie moet hier staan
  // (een test bewaakt dat); onbekende nieuwe instellingen verschijnen automatisch onder "Overig".
  const SETTINGS = [
    ["Klokprogramma en comfort", "mdi:clock-outline", [
      ["setpoint_dag", "Setpoint dag", "mdi:white-balance-sunny"],
      ["setpoint_nacht", "Setpoint nacht", "mdi:weather-night"],
      ["nacht_start", "Start nacht", "mdi:clock-start"],
      ["nacht_eind", "Einde nacht", "mdi:clock-end"],
      ["bedtijd", "Bedtijd (vloer warm)", "mdi:bed-clock"],
      ["tolerantie_laag", "Tolerantie te koud", "mdi:thermometer-minus"],
      ["tolerantie_hoog", "Tolerantie te warm", "mdi:thermometer-plus"],
      ["min_kamertemp", "Minimale kamertemperatuur", "mdi:thermometer-low"],
    ]],
    ["Voorverwarmen en stille uren", "mdi:volume-off", [
      ["voorverwarm_max", "Max voorverwarm-opslag", "mdi:clock-start"],
      ["stille_boost_max", "Max opslag stille uren", "mdi:arrow-up-bold"],
      ["stille_voorkeur", "Voorkeur stille uren", "mdi:volume-off"],
    ]],
    ["Stooklijn en weer", "mdi:chart-bell-curve-cumulative", [
      ["basis_temperatuur", "Basistemperatuur", "mdi:thermometer"],
      ["setpoint_offset", "Setpoint offset", "mdi:plus-minus-variant"],
      ["stooklijn", "Stooklijn helling", "mdi:chart-line-variant"],
      ["stooklijn_corr_min5", "Stooklijn correctie bij -5 °C", "mdi:thermometer-minus"],
      ["stooklijn_corr_5", "Stooklijn correctie bij 5 °C", "mdi:thermometer"],
      ["stooklijn_corr_15", "Stooklijn correctie bij 15 °C", "mdi:thermometer-plus"],
      ["horizon", "Weersverwachting horizon", "mdi:weather-cloudy-clock"],
      ["zon_factor", "Zoncompensatie", "mdi:white-balance-sunny"],
      ["bivalent_temp", "Bivalente temperatuur", "mdi:snowflake-thermometer"],
    ]],
    ["Frequentie en zacht draaien", "mdi:sine-wave", [
      ["max_freq_dag", "Max freq. dag (0 = uit)", "mdi:speedometer"],
      ["max_freq_stil", "Max freq. stil (0 = uit)", "mdi:speedometer-slow"],
      ["modulatie_marge", "Marge zacht draaien", "mdi:arrow-collapse-vertical"],
      ["min_freq", "Compressordrempel", "mdi:gauge-low"],
      ["stook_min", "Minimaal setpoint verwarmen (0 = uit)", "mdi:thermometer-chevron-up"],
    ]],
    ["Tekort-boost (kamer te koud)", "mdi:rocket-launch", [
      ["boost_tekort", "Boost bij tekort (°C)", "mdi:thermometer-minus"],
      ["boost_wachttijd", "Wachttijd voor boost (min)", "mdi:timer-outline"],
      ["boost_retour", "Doel retour (alleen zonder vloermodel)", "mdi:thermometer-high"],
      ["boost_freq", "Boost frequentie (Hz)", "mdi:speedometer"],
      ["boost_pauze", "Pauze tussen boosts (min)", "mdi:timer-pause-outline"],
    ]],
    ["Pomp-profiel (eigenschappen van jouw warmtepomp)", "mdi:heat-pump", [
      ["pomp_min_freq", "Minimale frequentie (0 = leren)", "mdi:speedometer-slow"],
      ["pomp_max_freq", "Maximale frequentie (0 = leren)", "mdi:speedometer"],
      ["pomp_start_verschil", "Startverschil setpoint - water", "mdi:arrow-up-bold"],
      ["pomp_stop_verschil", "Stopverschil water - setpoint", "mdi:arrow-down-bold"],
      ["pomp_min_vermogen", "Minimaal vermogen bij draaien (W)", "mdi:flash"],
      ["glycol", "Glycol (%)", "mdi:water-percent"],
    ]],
    ["Veiligheid en pomp", "mdi:shield-half-full", [
      ["min_setpoint", "Laagste setpoint (ook circulatie bij vorst)", "mdi:thermometer-low"],
      ["max_flow_temp", "Max aanvoertemperatuur", "mdi:thermometer-high"],
      ["vorst_buiten", "Vorstgrens buiten", "mdi:snowflake-alert"],
      ["vorst_retour", "Vorstgrens retour", "mdi:thermometer-low"],
      ["ontdooi_vooraf", "Niet uitzetten voor ontdooi (min)", "mdi:snowflake-melt"],
      ["ontdooi_wachttijd", "Wachttijd na ontdooien (min)", "mdi:timer-sand"],
      ["minimum_runtime", "Minimale draaitijd", "mdi:timer-play"],
      ["minimum_stilstand", "Minimale stilstandtijd", "mdi:timer-pause"],
      ["waakhond_marge", "Waakhond marge", "mdi:dog-service"],
      ["stookgrens", "Zomermodus stookgrens", "mdi:weather-sunny"],
    ]],
    ["Stroomprijs en zonnepanelen", "mdi:solar-power-variant", [
      ["max_stroomprijs", "Max stroomprijs", "mdi:currency-eur"],
      ["prijs_gevoeligheid", "Prijsgevoeligheid", "mdi:tune-variant"],
      ["pv_boost", "Zonnepanelen boost", "mdi:solar-power"],
      ["pv_drempel", "Zonnepanelen drempel", "mdi:solar-power-variant-outline"],
    ]],
    ["Opnieuw aanleren", "mdi:restart-alert", [
      ["herleer_percentage", "Hoeveel opnieuw aanleren (%)", "mdi:percent"],
    ]],
    ["Raam of deur open", "mdi:window-open-variant", [
      ["raam_vertraging", "Vertraging (min)", "mdi:timer-sand"],
    ]],
    ["Aanwezigheid", "mdi:home-export-outline", [
      ["afwezig_setpoint", "Setpoint afwezig", "mdi:home-export-outline"],
      ["afwezig_vertraging", "Vertraging (min)", "mdi:timer-sand"],
    ]],
    ["Netimport-limiet", "mdi:transmission-tower-import", [
      ["netimport_limiet", "Limiet (W, 0 = uit)", "mdi:transmission-tower-import"],
    ]],
    ["Warm tapwater", "mdi:water-boiler", [
      ["dhw_min_temp", "Minimum", "mdi:water-thermometer-outline"],
      ["dhw_doel_temp", "Doel", "mdi:water-thermometer"],
      ["dhw_legionella_temp", "Legionella temperatuur", "mdi:bacteria"],
      ["dhw_legionella_dagen", "Legionella interval (dagen)", "mdi:calendar-refresh"],
      ["dhw_max_looptijd", "Max looptijd (min)", "mdi:timer"],
    ]],
    ["Kosten", "mdi:cash", [
      ["vaste_stroomprijs", "Stroomprijs (vast contract, €/kWh)", "mdi:currency-eur"],
      ["graaddag_basis", "Graaddagen referentietemperatuur", "mdi:thermometer"],
    ]],
  ];
  const KNOWN = new Set(SETTINGS.flatMap((g) => g[2].map((r) => r[0])));

  // ------------------------------------------------------------------ views
  function overview(hass, inp) {
    const alerts = [
      { type: "tile", entity: `binary_sensor.${P}sensor_probleem`, name: "Sensorprobleem", icon: "mdi:alert-circle", color: "red",
        grid_options: { columns: 4 }, visibility: [{ condition: "state", entity: `binary_sensor.${P}sensor_probleem`, state: "on" }] },
      { type: "tile", entity: `sensor.${P}cop`, name: "COP laag tijdens draaien", icon: "mdi:chart-line-variant", color: "orange",
        grid_options: { columns: 4 }, visibility: [
          { condition: "numeric_state", entity: `sensor.${P}cop`, below: 2 },
          { condition: "numeric_state", entity: `sensor.${P}cop`, above: 0.01 },
          { condition: "state", entity: `binary_sensor.${P}defrost`, state: "off" }] },
      { type: "tile", entity: `binary_sensor.${P}defrost`, name: "Ontdooien bezig", icon: "mdi:snowflake-melt", color: "light-blue",
        grid_options: { columns: 4 }, visibility: [{ condition: "state", entity: `binary_sensor.${P}defrost`, state: "on" }] },
      { type: "tile", entity: `binary_sensor.${P}vorstbeveiliging`, name: "Vorstbeveiliging actief", icon: "mdi:snowflake-alert", color: "blue",
        grid_options: { columns: 4 }, visibility: [{ condition: "state", entity: `binary_sensor.${P}vorstbeveiliging`, state: "on" }] },
      { type: "tile", entity: `binary_sensor.${P}ijsvorming_alarm`, name: "Ijsvorming vermoed", icon: "mdi:snowflake-alert", color: "red",
        grid_options: { columns: 4 }, visibility: [{ condition: "state", entity: `binary_sensor.${P}ijsvorming_alarm`, state: "on" }] },
    ].filter((c) => ex(hass, c.entity));

    const T = (id, name, icon, color, cols, vertical) => tile(hass, `${id.includes(".") ? id : "sensor." + P + id}`, name, icon, color, cols, vertical);
    const B = (id, name, icon, color) => tile(hass, `binary_sensor.${P}${id}`, name, icon, color, 4, true);
    const SW = (id, name, icon, color) => tile(hass, `switch.${P}${id}`, name, icon, color);

    const sections = cards([
      alerts.length ? { type: "grid", column_span: 3, cards: alerts } : null,
      grid([
        heading("Regeling", "mdi:heat-pump", cards([badge(hass, `sensor.${P}cop`, "COP", null, "green"),
          badge(hass, inp.buiten, "Buiten", "mdi:sun-thermometer", "grey")])),
        ex(hass, CLIMATE) ? { type: "thermostat", entity: CLIMATE, name: "Warmtepomp regeling", show_current_as_primary: true,
          features: [{ type: "climate-preset-modes", style: "dropdown" }] } : null,
        SW("regeling_actief", "Slimme regeling", "mdi:brain", "green"),
        SW("leren_actief", "Blijft leren", "mdi:school", "purple"),
        SW("voorverwarmen_actief", "Voorverwarmen", "mdi:clock-start", "orange"),
        SW("modulatie_actief", "Zacht draaien", "mdi:speedometer-slow", "teal"),
        SW("prijssturing_actief", "Prijssturing", "mdi:currency-eur", "amber"),
        SW("vorstbeveiliging_actief", "Vorstbeveiliging", "mdi:snowflake-alert", "blue"),
        SW("tekort_boost_actief", "Tekort-boost", "mdi:rocket-launch", "orange"),
      ]),
      grid([
        heading("Wat doet de regeling nu", "mdi:robot-outline"),
        T("reden", "Reden", "mdi:robot-outline", "cyan", 12),
        T("plan", "Plan", "mdi:calendar-clock", "cyan", 12),
        T("setpoint", "Berekend setpoint", "mdi:calculator", "orange"),
        tile(hass, inp.pomp_setpoint, "Setpoint in pomp", "mdi:water-thermometer", "red"),
        tile(hass, inp.frequentie, "Compressor", "mdi:sine-wave", "purple", 12),
        B("voorverwarmen", "Voorverwarmen", "mdi:clock-start", "orange"),
        B("uitlopen", "Uitlopen", "mdi:timer-sand", "blue"),
        B("zacht_draaien", "Zacht", "mdi:speedometer-slow", "teal"),
        B("tekort_boost", "Boost", "mdi:rocket-launch", "orange"),
        B("freq_begrensd", "Freq.grens", "mdi:speedometer", "purple"),
        B("defrost", "Ontdooien", "mdi:snowflake-melt", "light-blue"),
        B("dure_stroom", "Dure stroom", "mdi:currency-eur-off", "red"),
        B("zomermodus", "Zomer", "mdi:weather-sunny", "amber"),
        B("sensor_probleem", "Sensor", "mdi:alert-circle", "red"),
      ]),
      grid([
        heading("Rendement", "mdi:chart-line"),
        T("cop", "COP nu", null, "green", 4, true),
        T("cop_vandaag", "Vandaag", null, "green", 4, true),
        T("cop_gisteren", "Gisteren", null, "green", 4, true),
        T("starts_vandaag", "Starts vandaag", "mdi:restart", "purple"),
        T("starts_gisteren", "Starts gisteren", "mdi:restart", "grey"),
        {
          type: "history-graph", title: "Stappen regeling (24 u)", hours_to_show: 24, grid_options: { columns: "full" },
          entities: cards([["voorverwarmen", "Voorverwarmen"], ["uitlopen", "Uitlopen"], ["zacht_draaien", "Zacht draaien"],
            ["tekort_boost", "Tekort-boost"], ["freq_begrensd", "Frequentiegrens"], ["dure_stroom", "Dure stroom"],
            ["defrost", "Ontdooien"]].map(([k, name]) => (ex(hass, `binary_sensor.${P}${k}`) ? { entity: `binary_sensor.${P}${k}`, name } : null))),
        },
      ]),
      grid([
        heading("Verloop (48 uur)", "mdi:chart-bell-curve"),
        graph(hass, { name: "Ruimtetemperatuur woonkamer", icon: "mdi:home-thermometer", hours: 48, entities: [
          { entity: inp.kamer, name: "Kamer", color: "#FB923C" },
          { entity: CLIMATE, name: "Setpoint", color: "#38BDF8", attribute: "temperature" }], noMini: false }),
        graph(hass, { name: "Vloer en setpoint pomp", icon: "mdi:heating-coil", hours: 48, entities: [
          { entity: `sensor.${P}vloer_gemeten`, name: "Vloer (gemeten)", color: "#A78BFA" },
          { entity: `sensor.${P}vloer_geschat`, name: "Vloer (regeling)", color: "#C4B5FD" },
          { entity: S, name: "Berekend setpoint", color: "#FB923C" },
          { entity: inp.pomp_setpoint, name: "In de pomp", color: "#F87171" },
          { entity: inp.retour, name: "Retour", color: "#38BDF8" }] }),
        graph(hass, { name: "Vermogen", icon: "mdi:flash", hours: 48, fill: "fade", entities: [
          { entity: `sensor.${P}elektrisch_vermogen`, name: "Elektrisch (W)", color: "#FBBF24" },
          { entity: `sensor.${P}thermisch_vermogen`, name: "Thermisch (kW)", color: "#F87171", y2: true }] }),
      ], { column_span: 3 }),
    ]);

    const badges = cards([
      badge(hass, inp.buiten, "Buiten nu", "mdi:sun-thermometer", "grey"),
      badge(hass, `sensor.${P}voorspelde_buiten_temp`, "Verwacht buiten", "mdi:thermometer-auto", "blue"),
      badge(hass, `sensor.${P}voorspelde_afkoeling`, "Verw. afkoeling", "mdi:thermometer-minus", "light-blue"),
      badge(hass, `sensor.${P}kamer_na_bedtijd`, "Kamer na bedtijd", "mdi:bed-clock", "pink"),
      badge(hass, `sensor.${P}vloer_gemeten`, "Vloer (gemeten)", "mdi:heating-coil", "purple"),
      badge(hass, S, "Water setpoint", "mdi:water-thermometer", "orange"),
      badge(hass, `sensor.${P}cop_vandaag`, "COP vandaag", "mdi:chart-line", "green"),
      badge(hass, inp.retour, "Retour wp", "mdi:heat-pump-outline", "accent"),
      badge(hass, inp.aanvoer, "Aanvoer wp", "mdi:heat-pump-outline", "red"),
    ]);
    return {
      title: "Slimme WP Overzicht", path: "slimme-overzicht", icon: "mdi:heat-pump", type: "sections", max_columns: 3,
      header: { layout: "center", badges_position: "bottom", card: { type: "markdown", text_only: true, content:
        `{% set c = '${CLIMATE}' %}\n# {{ state_attr(c,'current_temperature') }} °C\n` +
        `Doel **{{ state_attr(c,'temperature') }} °C**{% if state_attr(c,'preset_mode') %} · {{ state_attr(c,'preset_mode') }}{% endif %}\n\n` +
        `**Nu:** {{ states('sensor.${P}reden') }}<br>\n**Plan:** {{ states('sensor.${P}plan') }}` } },
      badges, sections,
    };
  }

  function learning(hass, inp) {
    const T = (id, name, icon, color, cols) => tile(hass, `sensor.${P}${id}`, name, icon, color, cols);
    const buiten = inp.buiten || `sensor.${P}voorspelde_buiten_temp`;
    const tables = [
      heading("Geleerde tabellen", "mdi:table"),
      markdown("Frequentie per verschil",
        `{% set t = state_attr('${S}','frequentie_tabel') %}\n` +
        `{% set b = state_attr('${S}','frequentie_tabel_bron') %}\n` +
        `{% set w = state_attr('${S}','frequentie_tabel_kw') %}\n` +
        `{% set m = state_attr('${S}','modulatie_minimaal_verschil') %}\n` +
        `{% set lo = state_attr('${S}','pomp_min_frequentie') %}\n` +
        `{% set hi = state_attr('${S}','pomp_max_frequentie') %}\n` +
        `{% set v = state_attr('${S}','verschil_voor_max_frequentie') %}\n` +
        `{% if t %}\n| Verschil setpoint - retour | Frequentie | Thermisch | Bron |\n|---|---|---|---|\n` +
        `{% for k, f in t.items() %}| {{ k }} K | {{ f }} Hz | {{ (w[k] ~ ' kW') if w and k in w else '-' }} | {{ b[k] if b and k in b else '-' }} |\n{% endfor %}\n` +
        `Bereik van de pomp: **{{ lo }} - {{ hi }} Hz**{% if v is not none %}, vol vermogen vanaf **+{{ v }} K**{% endif %}.\n\n` +
        `Minimaal verschil dat de compressor aan houdt: **{{ m }} K**\n{% else %}Nog niet genoeg gegevens geleerd.{% endif %}`),
      markdown("Verwacht setpoint komende uren",
        `{% set f = state_attr('${S}','verwacht_setpoint') %}\n{% if f %}\n` +
        `| Tijd | Buiten | Kamerdoel | Vloer nodig | Setpoint WP |\n|---|---|---|---|---|\n` +
        `{% for r in f %}| {{ r.tijd }} | {{ r.buiten }} °C | {{ r.kamerdoel }} °C | {{ r.vloer }} °C | {{ r.setpoint }} °C |\n{% endfor %}\n` +
        `Uit de weersvoorspelling en zon; de planner kan voorverwarmen of uitlopen erbovenop.\n{% else %}Nog niet genoeg data.{% endif %}`),
      markdown("Vloer en setpoint per buitentemperatuur",
        `{% set t = state_attr('${S}','vloer_setpoint_tabel') %}\n{% if t %}\n{% set k = t['0'].kamer.keys() | list %}\n` +
        `| Buiten | Kamer {{ k[0] }} | Kamer {{ k[1] }} | Kamer {{ k[2] }} |\n|---|---|---|---|\n` +
        `{% for b, v in t.items() %}| {{ b }} °C | vloer {{ v.kamer[k[0]].vloer }} / WP {{ v.kamer[k[0]].setpoint }} (berekend {{ v.kamer[k[0]].get('berekend', '-') }}) ` +
        `| vloer {{ v.kamer[k[1]].vloer }} / WP {{ v.kamer[k[1]].setpoint }} (berekend {{ v.kamer[k[1]].get('berekend', '-') }}) ` +
        `| vloer {{ v.kamer[k[2]].vloer }} / WP {{ v.kamer[k[2]].setpoint }} (berekend {{ v.kamer[k[2]].get('berekend', '-') }}) |\n{% endfor %}\n` +
        `WP = setpoint dat naar de pomp gaat (na Laagste setpoint {{ states('${n("min_setpoint")}') }} °C); berekend = wat de regeling zelf nodig vindt.\n\n` +
        `Nu: kamer {{ state_attr('${CLIMATE}','current_temperature') }} °C, vloer {{ states('sensor.${P}vloer_gemeten') }} °C, ` +
        `buiten {{ states('${buiten}') }} °C\n{% else %}Nog niet genoeg data.{% endif %}`),
      markdown("Geleerde stooklijn",
        `{% set c = state_attr('${S}','geleerde_stooklijn') %}\n{% if c %}\n| Buiten | Water |\n|---|---|\n` +
        `{% for k, v in c.items() %}| {{ k }} °C | {{ v }} °C |\n{% endfor %}\n` +
        `Eigen correctie op de stooklijn: {{ state_attr('${S}','stooklijn_handmatig') }} °C (instellingen), geleerde correctie {{ state_attr('${S}','stooklijn_correctie') }} °C.\n` +
        `{% else %}Het model is nog niet betrouwbaar genoeg.{% endif %}`),
    ];
    for (const t of tables) { if (!t.grid_options) t.grid_options = { columns: "full" }; }
    return {
      title: "Slimme WP Leren", path: "slimme-leren", icon: "mdi:brain", type: "sections", max_columns: 3,
      sections: cards([
        grid([
          heading("Wat leert de regeling", "mdi:brain"),
          T("modelvertrouwen", "Modelvertrouwen", "mdi:shield-check", "green", 12),
          T("tijdconstante_huis", "Afkoeltijd huis", "mdi:home-clock", "blue"),
          T("tijdconstante_vloer", "Afkoeltijd vloer", "mdi:heating-coil", "purple"),
          T("vloer_gemeten", "Vloer (gemeten)", "mdi:thermometer", "orange"),
          T("vloer_bron", "Bron vloertemperatuur", "mdi:thermometer-check", "grey"),
          T("stooklijn_correctie", "Stooklijn geleerd (+/-)", "mdi:chart-bell-curve-cumulative", "orange"),
          T("vloer_tekort", "Vloer warmtetekort", "mdi:heating-coil", "red"),
          T("avond_bias", "Avondcorrectie", "mdi:weather-night", "indigo"),
          T("kamer_na_bedtijd", "Kamer 1 u na bedtijd", "mdi:bed-clock", "pink", 12),
        ]),
        grid([
          heading("Weer", "mdi:weather-partly-cloudy"),
          tile(hass, inp.buiten, "Buiten nu", "mdi:sun-thermometer", "grey"),
          T("voorspelde_buiten_temp", "Verwacht buiten", "mdi:thermometer-auto", "blue"),
          T("voorspelde_afkoeling", "Voorspelde afkoeling", "mdi:thermometer-minus", "light-blue"),
          T("zon_reductie", "Zonbijdrage", "mdi:white-balance-sunny", "amber"),
          heading("Energie", "mdi:lightning-bolt"),
          T("energie_thermisch", "Thermisch", "mdi:fire", "red"),
          T("energie_elektrisch", "Elektrisch", "mdi:flash", "amber"),
          T("cop_seizoen", "Gemiddelde COP", "mdi:chart-line", "green", 12),
        ]),
        { type: "grid", column_span: 3, cards: tables },
        grid([
          heading("Grafieken", "mdi:chart-bell-curve"),
          graph(hass, { name: "Modelvertrouwen en voorspelling", icon: "mdi:brain", hours: 168, pph: 1, entities: [
            { entity: `sensor.${P}modelvertrouwen`, name: "Modelvertrouwen", color: "#4ADE80" },
            { entity: `sensor.${P}kamer_na_bedtijd`, name: "Kamer 1 u na bedtijd", color: "#FB923C", y2: true }] }),
          graph(hass, { name: "Frequentie en retour", icon: "mdi:sine-wave", hours: 24, entities: [
            { entity: inp.frequentie, name: "Frequentie (Hz)", color: "#A78BFA" },
            { entity: inp.retour, name: "Retour", color: "#38BDF8", y2: true },
            { entity: inp.pomp_setpoint, name: "Setpoint", color: "#F87171", y2: true }] }),
          graph(hass, { name: "COP", icon: "mdi:chart-line", hours: 72, pph: 2, entities: [
            { entity: `sensor.${P}cop`, name: "Huidig", color: "#4ADE80" },
            { entity: `sensor.${P}cop_vandaag`, name: "Vandaag", color: "#2DD4BF" }] }),
          graph(hass, { name: "Compressorstarts per dag", icon: "mdi:restart", hours: 168, bar: true, entities: [
            { entity: `sensor.${P}starts_vandaag`, name: "Starts", color: "#A78BFA" }] }),
        ], { column_span: 3 }),
      ]),
    };
  }

  function settingsView(hass) {
    const groups = SETTINGS.map(([title, icon, list]) => {
      const e = entitiesCard(hass, list.map(([k, name, ic]) => [n(k), name, ic]));
      return e ? [heading(title, icon), e] : null;
    }).filter(Boolean);
    const other = Object.keys(hass.states).filter((id) => id.startsWith(`number.${P}`) && !KNOWN.has(id.slice(`number.${P}`.length)));
    if (other.length) {
      groups.push([heading("Overig", "mdi:dots-horizontal"),
        { type: "entities", show_header_toggle: false, entities: other.sort().map((entity) => ({ entity })) }]);
    }
    // spreid de groepen over drie kolommen met ongeveer evenveel rijen
    const cols = [[], [], []], load = [0, 0, 0];
    for (const g of groups) {
      const i = load.indexOf(Math.min(...load));
      cols[i].push(...g);
      load[i] += g[1].entities.length + 2;
    }
    const sw = (id, name) => (ex(hass, `switch.${P}${id}`) ? { entity: `switch.${P}${id}`, name } : null);
    const extra = cards([
      heading("Aan en uit", "mdi:toggle-switch"),
      { type: "entities", show_header_toggle: false, entities: cards([
        sw("regeling_actief", "Slimme regeling"), sw("leren_actief", "Blijft leren"), sw("voorverwarmen_actief", "Voorverwarmen"),
        sw("modulatie_actief", "Zacht draaien"), sw("prijssturing_actief", "Prijssturing"), sw("tekort_boost_actief", "Tekort-boost"),
        sw("vorstbeveiliging_actief", "Vorstbeveiliging"), sw("dhw_actief", "Tapwatersturing"),
        sw("kosten_vaste_prijs", "Kosten met vaste prijs"),
        ex(hass, `button.${P}opnieuw_aanleren`) ? { entity: `button.${P}opnieuw_aanleren`, name: "Opnieuw aanleren starten", icon: "mdi:restart-alert" } : null,
      ]) },
    ]);
    cols[0].unshift(...extra);
    return {
      title: "Slimme WP Instellingen", path: "slimme-instellingen", icon: "mdi:tune", type: "sections", max_columns: 3,
      sections: cols.filter((c) => c.length).map((c) => ({ type: "grid", cards: c })),
    };
  }

  function pumpView(hass, inp) {
    const t = (entity, name, icon, color, cols) => tile(hass, entity, name, icon, color, cols);
    const sec = [
      grid([
        heading("Bediening", "mdi:tune-vertical"),
        t(inp.pomp_schakelaar, "Warmtepomp aan/uit", "mdi:power", "red", 12),
        t(inp.pomp_setpoint, "Setpoint in de pomp", "mdi:water-thermometer", "red", 12),
      ]),
      grid([
        heading("Water en vermogen", "mdi:water-thermometer"),
        t(inp.aanvoer, "Aanvoer", "mdi:thermometer-chevron-up", "red"),
        t(inp.retour, "Retour", "mdi:thermometer-chevron-down", "blue"),
        t(inp.vloer, "Vloer", "mdi:heating-coil", "purple"),
        t(inp.debiet_1, "Flow 1", "mdi:pump", "teal"),
        t(inp.debiet_2, "Flow 2", "mdi:pump", "teal"),
        tile(hass, `sensor.${P}thermisch_vermogen`, "Thermisch", "mdi:fire", "deep-orange"),
        tile(hass, `sensor.${P}elektrisch_vermogen`, "Elektrisch", "mdi:flash", "amber"),
        tile(hass, `sensor.${P}cop`, "COP", "mdi:chart-line", "green", 12),
      ]),
      grid([
        heading("Compressor en omgeving", "mdi:chip"),
        t(inp.frequentie, "Frequentie", "mdi:sine-wave", "purple"),
        t(inp.stroom, "Stroomsterkte", "mdi:current-ac", "amber"),
        t(inp.spanning, "Spanning", "mdi:flash-triangle-outline", "amber"),
        t(inp.vermogen, "Vermogen (meter)", "mdi:meter-electric", "amber"),
        t(inp.buiten, "Buiten", "mdi:sun-thermometer", "grey"),
        t(inp.buiten_unit, "Buitensensor pomp", "mdi:thermometer-auto", "grey"),
        t(inp.coil, "Coil", "mdi:snowflake-thermometer", "light-blue"),
        t(inp.tank, "Tapwatervat", "mdi:water-boiler", "blue"),
        t(inp.zonnepanelen, "Zonnepanelen", "mdi:solar-power", "amber"),
        t(inp.net, "Netvermogen", "mdi:transmission-tower", "grey"),
      ]),
      grid([
        heading("Ontdooien en ijsvorming", "mdi:snowflake-melt"),
        tile(hass, `sensor.${P}ijsvorming`, "Ijsvorming", "mdi:snowflake-alert", "red", 6),
        tile(hass, `sensor.${P}volgende_ontdooi`, "Volgende ontdooi (min)", "mdi:snowflake-melt", "light-blue", 6),
        tile(hass, `sensor.${P}ontdooi_piek`, "Coil-piek laatste ontdooi", "mdi:snowflake-thermometer", "orange", 6),
        tile(hass, `binary_sensor.${P}ijsvorming_alarm`, "Ijsalarm", "mdi:alert-circle", "red", 6),
        markdown("Geleerd over het ontdooien",
          `{% set o = state_attr('${S}','ontdooien') %}\n{% set k = state_attr('${S}','ontdooi_kwaliteit') %}\n{% set i = state_attr('${S}','ijsvorming') %}\n` +
          `{% if o and o.aantal %}\n| | |\n|---|---|\n| Gemeten ontdooicycli | {{ o.aantal }} |\n| Duur | {{ o.duur_min }} min |\n` +
          `| Interval | {{ o.interval_min }} min |\n| Herstel daarna | {{ o.herstel_min }} min |\n` +
          `{% if k %}| Coil-piek (normaal) | {{ k.referentie_piek }} °C |\n| Zwakke ontdooicycli achter elkaar | {{ k.zwakke_reeks }} |\n{% endif %}` +
          `{% if i %}| COP direct na ontdooien | {{ i.cop_na_ontdooien }} |\n| Redenen ijsmelding | {{ i.redenen | join(', ') if i.redenen else 'geen' }} |\n{% endif %}` +
          `{% else %}Nog geen ontdooicycli gemeten.{% endif %}`, "full"),
        graph(hass, { name: "Coil en aanvoer rond ontdooien", icon: "mdi:snowflake-melt", hours: 6, pph: 30, entities: [
          { entity: inp.coil, name: "Coil", color: "#38BDF8" }, { entity: inp.aanvoer, name: "Aanvoer", color: "#F87171" },
          { entity: inp.buiten_unit, name: "Buitensensor pomp", color: "#A78BFA" }] }),
        graph(hass, { name: "Coil-piek per ontdooi (7 dagen)", icon: "mdi:snowflake-thermometer", hours: 168, pph: 2, points: true, entities: [
          { entity: `sensor.${P}ontdooi_piek`, name: "Piek (gezond 25-45)", color: "#FB923C" }] }),
        ex(hass, `binary_sensor.${P}defrost`) ? { type: "history-graph", title: "Ontdooien en ijsalarm (24 u)", hours_to_show: 24,
          grid_options: { columns: "full" }, entities: cards([`binary_sensor.${P}defrost`, `binary_sensor.${P}ijsvorming_alarm`]
            .filter((e) => ex(hass, e)).map((entity) => ({ entity }))) } : null,
      ]),
      grid([
        heading("Grafieken (24 uur)", "mdi:chart-bell-curve"),
        graph(hass, { name: "Aanvoer en retour", icon: "mdi:heat-pump", hours: 24, fill: "fade", columns: 6, entities: [
          { entity: inp.aanvoer, name: "Aanvoer", color: "#F87171" }, { entity: inp.retour, name: "Retour", color: "#38BDF8" }] }),
        graph(hass, { name: "Compressor", icon: "mdi:sine-wave", hours: 24, columns: 6, entities: [
          { entity: inp.frequentie, name: "Frequentie (Hz)", color: "#A78BFA" },
          { entity: inp.stroom, name: "Stroom (A)", color: "#FBBF24", y2: true }] }),
        graph(hass, { name: "Flow", icon: "mdi:pump", hours: 24, fill: "fade", columns: 6, entities: [
          { entity: inp.debiet_1, name: "Flow 1", color: "#2DD4BF" }, { entity: inp.debiet_2, name: "Flow 2", color: "#38BDF8" }] }),
        graph(hass, { name: "Energieverbruik", icon: "mdi:flash", hours: 24, pph: 2, fill: "fade", columns: 6, entities: [
          { entity: inp.vermogen || `sensor.${P}elektrisch_vermogen`, name: "Vermogen", color: "#FBBF24" }] }),
      ], { column_span: 3 }),
    ];
    return { title: "Warmtepomp", path: "warmtepomp", icon: "mdi:engine", type: "sections", max_columns: 3, sections: cards(sec) };
  }

  function costView(hass) {
    const T = (id, name, icon, color, cols, vertical) => tile(hass, `sensor.${P}${id}`, name, icon, color, cols, vertical);
    const sw = (id, name, icon, color, cols) => tile(hass, `switch.${P}${id}`, name, icon, color, cols);
    return {
      title: "Kosten & analyse", path: "kosten-analyse", icon: "mdi:cash-multiple", type: "sections", max_columns: 3,
      badges: cards([badge(hass, n("vaste_stroomprijs"), "Stroomprijs", null, "amber")]),
      sections: cards([
        grid([
          heading("Kosten warmtepomp", "mdi:cash"),
          T("kosten_dag", "Vandaag", "mdi:calendar-today", "green", 6), T("kosten_week", "Deze week", "mdi:calendar-week", "green", 6),
          T("kosten_maand", "Deze maand", "mdi:calendar-month", "green", 6), T("kosten_jaar", "Dit jaar", "mdi:calendar", "green", 6),
          T("energie_dag", "kWh vandaag", "mdi:flash", "amber", 4, true), T("energie_week", "kWh week", "mdi:flash", "amber", 4, true),
          T("energie_maand", "kWh maand", "mdi:flash", "amber", 4, true),
          stats(hass, `sensor.${P}kosten_dag`, "Kosten per dag (30 dagen)", "day", "max", "bar", 30),
          entitiesCard(hass, [[n("vaste_stroomprijs"), "Stroomprijs (vast contract, €/kWh)", "mdi:currency-eur"],
            [`switch.${P}kosten_vaste_prijs`, "Kosten met vaste prijs"], [n("graaddag_basis"), "Graaddagen referentietemperatuur", "mdi:thermometer"]]),
        ]),
        grid([
          heading("Efficiëntie", "mdi:chart-timeline-variant"),
          T("graaddagen_dag", "Graaddagen vandaag", "mdi:thermometer-minus", "blue", 6), T("graaddagen_maand", "Graaddagen maand", "mdi:thermometer-minus", "blue", 6),
          T("kwh_per_graaddag", "kWh/graaddag vandaag", "mdi:chart-timeline-variant", "purple", 6),
          T("kwh_per_graaddag_week", "kWh/graaddag week", "mdi:chart-timeline-variant", "purple", 6),
          T("cop_vandaag", "COP vandaag", "mdi:chart-line", "green", 6), T("cop_seizoen", "COP seizoen", "mdi:chart-line", "green", 6),
          stats(hass, `sensor.${P}energie_elektrisch`, "Verbruik per dag (kWh)", "day", "change", "bar", 30),
        ]),
        grid([
          heading("Compressor & ontdooien", "mdi:sine-wave"),
          T("draaitijd_vandaag", "Draaitijd vandaag", "mdi:timer-play", "purple", 6), T("starts_vandaag", "Starts vandaag", "mdi:restart", "purple", 6),
          T("draaitijd_per_start", "Gem. per start", "mdi:timer-outline", "teal", 12),
          T("ontdooien_vandaag", "Ontdooiingen vandaag", "mdi:snowflake-melt", "light-blue", 6),
          T("ontdooien_7_dagen", "Ontdooiingen 7 dagen", "mdi:snowflake-melt", "light-blue", 6),
          ex(hass, `binary_sensor.${P}defrost`) ? markdown(null,
            `{% set d = states.binary_sensor.${P}defrost %}{% if d %}Laatste wijziging ontdooien: **{{ relative_time(d.last_changed) }} geleden** ` +
            `({{ as_timestamp(d.last_changed) | timestamp_custom('%H:%M') }}){% endif %}`) : null,
          ex(hass, `binary_sensor.${P}defrost`) ? { type: "history-graph", title: "Compressor & ontdooien (24 u)", hours_to_show: 24,
            grid_options: { columns: "full" }, entities: cards([`binary_sensor.${P}defrost`].map((entity) => ({ entity, name: "Ontdooien" }))) } : null,
        ]),
        grid([
          heading("Slimme regeling vs. schaduwmodus", "mdi:scale-balance"),
          markdown(null, "Zet de slimme regeling een week uit (schaduwmodus) en vergelijk daarna de weken. " +
            "**Lager kWh per graaddag = zuiniger**, los van hoe koud het was."),
          sw("regeling_actief", "Slimme regeling", "mdi:brain", "green", 12),
          T("kwh_graaddag_regeling", "kWh/graaddag regeling aan (28 d)", "mdi:brain", "green", 6),
          T("kwh_graaddag_schaduw", "kWh/graaddag regeling uit (28 d)", "mdi:brain", "grey", 6),
          stats(hass, `sensor.${P}kwh_per_graaddag`, "kWh per graaddag per week (12 weken)", "week", "mean", "bar", 84),
          stats(hass, `sensor.${P}cop_vandaag`, "COP per dag (30 dagen)", "day", "max", "line", 30),
          ex(hass, `switch.${P}regeling_actief`) ? { type: "history-graph", title: "Slimme regeling aan/uit (30 dagen)", hours_to_show: 720,
            grid_options: { columns: "full" }, entities: [{ entity: `switch.${P}regeling_actief`, name: "Slimme regeling" }] } : null,
        ], { column_span: 3 }),
      ]),
    };
  }

  // ------------------------------------------------------------------ strategy
  function build(hass) {
    const inp = inputs(hass);
    if (!ex(hass, S)) {
      return { title: "Slimme Warmtepomp", views: [{ title: "Slimme WP", path: "slimme-wp", cards: [{
        type: "markdown", content: "De integratie **Slimme Warmtepomp** is niet geladen of heeft nog geen entiteiten. " +
          "Controleer Instellingen > Apparaten & diensten en laad dit dashboard daarna opnieuw." }] }] };
    }
    return { title: "Slimme Warmtepomp", views: [overview(hass, inp), learning(hass, inp), settingsView(hass), pumpView(hass, inp), costView(hass)] };
  }

  class SlimmeWarmtepompDashboardStrategy extends (root.HTMLElement || class {}) {
    static async generate(config, hass) {
      try {
        return build(hass);
      } catch (err) {
        return { title: "Slimme Warmtepomp", views: [{ title: "Fout", path: "fout", cards: [{
          type: "markdown", content: `Het dashboard kon niet worden opgebouwd: ${err && err.message}` }] }] };
      }
    }
    static async getCreateSuggestions() {
      return { title: "Slimme Warmtepomp", icon: "mdi:heat-pump" };
    }
  }

  if (root.customElements && !root.customElements.get("ll-strategy-dashboard-slimme-warmtepomp")) {
    root.customElements.define("ll-strategy-dashboard-slimme-warmtepomp", SlimmeWarmtepompDashboardStrategy);
  }
  root.customStrategies = root.customStrategies || [];
  if (!root.customStrategies.some((s) => s.type === "slimme-warmtepomp")) {
    root.customStrategies.push({
      type: "slimme-warmtepomp", strategyType: "dashboard", name: "Slimme Warmtepomp",
      description: "Complete dashboard voor de integratie Slimme Warmtepomp: overzicht, leren, instellingen, pomp en kosten.",
      documentationURL: "https://github.com/SvLogchem/SmartHeatpump",
    });
  }
  root.SlimmeWarmtepompDashboard = { build, SETTINGS };
})();
