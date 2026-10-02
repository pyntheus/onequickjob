#!/usr/bin/env node
// Runs the prototype's own category and pricing code (docs/design/prototype.jsx) in Node,
// so the Python port can be checked against the original JavaScript, Math.round and all.
//
//   node scripts/prototype-extract.mjs catalogue   > seed/catalogue.prototype.json
//   node scripts/prototype-extract.mjs cases [n]   > api/tests/fixtures/prototype_cases.json
//
// Only plain-JS blocks are evaluated (no JSX): GROUPS..EXCLUDED and HOURLY..estimateFor.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const src = readFileSync(join(root, "docs/design/prototype.jsx"), "utf8");

function block(start, end) {
  const i = src.indexOf(start);
  const j = src.indexOf(end, i);
  if (i < 0 || j < 0) throw new Error(`block ${start} .. ${end} not found`);
  return src.slice(i, j);
}

const code = [
  block("const GROUPS = [", "const CAT_ICONS"),
  block("const HOURLY = 45;", "const LAWNS"),
  "return { GROUPS, DOCS, CATEGORIES, EXCLUDED, PRICING_MODELS, estimateFor, HOURLY };",
].join("\n");
const P = new Function(code)();

// Instrument Math.round: flag calls where float error put the value a hair off .5
// (e.g. 138 / 60 * 45 = 103.49999999999999). There JavaScript rounds the float noise,
// while the Python port rounds the exact value half-up, as decisions.md requires.
const jsRound = Math.round;
let nearHalf = false;
Math.round = (x) => {
  const f = x - Math.floor(x);
  if (f !== 0.5 && Math.abs(f - 0.5) < 1e-9) nearHalf = true;
  return jsRound(x);
};

// mulberry32, as in the prototype, so generated cases are reproducible.
function mulberry32(seed) {
  return function () {
    seed |= 0; seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const defaultsFor = (cat) => Object.fromEntries(cat.intake.map((f) => [f.key, f.default]));

function randomAnswers(cat, r) {
  const a = {};
  for (const f of cat.intake) {
    const pick = (xs) => xs[Math.floor(r() * xs.length)];
    if (f.type === "choice" || f.type === "chips") a[f.key] = pick(f.options).value;
    else if (f.type === "multi") a[f.key] = f.options.filter(() => r() < 0.45).map((o) => o.value);
    else if (f.type === "number") {
      const steps = Math.floor((f.max - f.min) / f.step);
      a[f.key] = f.min + Math.floor(r() * (steps + 1)) * f.step;
    } else if (f.type === "counts") a[f.key] = Object.fromEntries(f.items.map((it) => [it.key, Math.floor(r() * 4)]));
    else if (f.type === "text") a[f.key] = "";
    else if (f.type === "photos") a[f.key] = 0;
  }
  return a;
}

function run(cat, answers, area) {
  nearHalf = false;
  const e = P.estimateFor(cat, answers, area);
  const pence = (v) => (v == null ? null : Math.round(v * 100));
  return {
    price_pence: pence(e.price),
    first_pence: pence(e.first),
    mins: e.mins,
    first_mins: e.firstMins ?? null,
    low_pence: pence(Math.round(e.price * e.spread[0])),
    high_pence: pence(Math.round(e.price * e.spread[1])),
    spread: e.spread,
    confidence: e.confidence,
    unit: e.unit,
    note: e.note ?? null,
    first_reason: e.firstReason ?? null,
    conf_note: e.confNote ?? null,
    float_half_boundary: nearHalf,
  };
}

// Prototype answers hold a photo *count*; the real app holds file ids.
const portable = (answers) =>
  Object.fromEntries(Object.entries(answers).map(([k, v]) => [k, typeof v === "number" && k === "photos" ? [] : v]));

const mode = process.argv[2];
if (mode === "catalogue") {
  process.stdout.write(JSON.stringify({ groups: P.GROUPS, documents: P.DOCS, categories: P.CATEGORIES, excluded: P.EXCLUDED, hourly: P.HOURLY }, null, 2) + "\n");
} else if (mode === "cases") {
  const n = Number(process.argv[3] || 400);
  const r = mulberry32(20261002);
  const cases = [];
  const lawnAreas = [40, 85, 190, 350, 32, 68, 152, 280, 48, 102, 228, 420, 186, 1, 600];
  for (const cat of P.CATEGORIES) {
    const area = cat.measure === "lawn" ? 186 : null;
    cases.push({ category: cat.id, kind: "default", area_m2: area, answers: portable(defaultsFor(cat)), expected: run(cat, defaultsFor(cat), area) });
    for (let i = 0; i < n; i++) {
      const answers = randomAnswers(cat, r);
      const a = cat.measure === "lawn" ? (i < lawnAreas.length ? lawnAreas[i] : 1 + Math.floor(r() * 600)) : null;
      cases.push({ category: cat.id, kind: "random", area_m2: a, answers: portable(answers), expected: run(cat, answers, a) });
    }
  }
  process.stdout.write(JSON.stringify({ source: "docs/design/prototype.jsx", generator: "scripts/prototype-extract.mjs", cases }) + "\n");
} else {
  console.error("usage: prototype-extract.mjs catalogue | cases [n]");
  process.exit(2);
}
