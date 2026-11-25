// Draait de dashboard-strategy tegen een nagebootste hass (stdin: {states, mini}) en rapporteert (stdout: JSON).
const fs = require("fs");
const vm = require("vm");
const input = JSON.parse(fs.readFileSync(0, "utf8"));
const file = process.argv[2];
const defined = {};
const ctx = {
  console,
  HTMLElement: class {},
  customElements: {
    define: (name, cls) => { defined[name] = cls; },
    get: (name) => (name === "mini-graph-card" && input.mini ? class {} : defined[name]),
  },
};
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(file, "utf8"), ctx);

const refs = [];
const walk = (node, where) => {
  if (Array.isArray(node)) return node.forEach((x) => walk(x, where));
  if (node && typeof node === "object") {
    if (typeof node.entity === "string") refs.push([node.entity, where]);
    if (Array.isArray(node.entities)) node.entities.forEach((e) => { if (typeof e === "string") refs.push([e, where]); });
    Object.values(node).forEach((v) => walk(v, where));
  }
};

(async () => {
  const strategy = defined["ll-strategy-dashboard-slimme-warmtepomp"];
  const cfg = await strategy.generate({}, { states: input.states, language: input.language });
  JSON.stringify(cfg);                       // must be serialisable
  const views = cfg.views || [];
  views.forEach((v) => walk(v, v.title));
  const sections = views.map((v) => ({ title: v.title, path: v.path, cards: JSON.stringify(v).split('"type":"').length - 1 }));
  const text = JSON.stringify(cfg);
  // texts the viewer sees: names/titles/headings of the Dutch build must all have an English counterpart; markdown content as is
  const names = new Set(), markdown = [];
  const KEYS = new Set(["name", "title", "heading", "label"]);
  const collect = (node) => {
    if (Array.isArray(node)) return node.forEach(collect);
    if (node && typeof node === "object") {
      if (node.type === "markdown" && typeof node.content === "string") markdown.push(node.content);
      for (const [k, v] of Object.entries(node)) { if (typeof v === "string" && KEYS.has(k)) names.add(v); else collect(v); }
    }
  };
  collect(cfg);
  const buttons = [];
  const findButtons = (node) => {
    if (Array.isArray(node)) return node.forEach(findButtons);
    if (node && typeof node === "object") {
      if (node.type === "button") buttons.push({ entity: node.entity, confirmation: !!(node.tap_action && node.tap_action.confirmation) });
      Object.values(node).forEach(findButtons);
    }
  };
  findButtons(cfg);
  const EN = ctx.SlimmeWarmtepompDashboard.EN;
  const untranslated = [...names].filter((x) => x && !(x in EN) && !/^(Kamer|Ruimte|Flow) \d+$/.test(x));
  const settings = ctx.SlimmeWarmtepompDashboard.SETTINGS.flatMap((g) => g[2].map((r) => r[0]));
  console.log(JSON.stringify({
    title: cfg.title, views: sections,
    missing: refs.filter(([id]) => !(id in input.states)).map(([id, w]) => `${id} (${w})`),
    strategies: ctx.customStrategies.map((s) => s.type), element: Object.keys(defined),
    settings, text_has_mini: text.includes("custom:mini-graph-card"), text_has_history: text.includes("history-graph"),
    overig: text.includes('"heading":"Overig"'), cfg_entities: refs.map(([id]) => id),
    first_view_title: views[0] && views[0].title, names: [...names], markdown, untranslated, buttons,
  }));
  // a second call with an empty state machine must give the explanatory page, not throw
  const empty = await strategy.generate({}, { states: {}, language: input.language });
  const expected = input.language && !input.language.startsWith("nl") ? "not loaded" : "niet geladen";
  if (!empty.views || !JSON.stringify(empty).includes(expected)) throw new Error("empty hass not handled");
})().catch((e) => { console.error(e); process.exit(1); });
