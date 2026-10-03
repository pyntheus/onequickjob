/** API fixtures for L1's screen tests (shapes from the generated schema). */
import type { Schemas } from "../api/client";

export const me = {
  user_id: "u1",
  name: "Sarah Whitfield",
  phone: "07700 900123",
  email: null,
  roles: ["customer"],
  customer_id: "c1",
  provider_id: null,
  helper_of: null,
  home_path: "/account",
};

const field = (f: Partial<Schemas["IntakeField"]> & Pick<Schemas["IntakeField"], "key" | "type" | "label">) =>
  ({ hint: null, placeholder: null, options: null, items: null, unit: null, unit1: null, min: null, max: null, step: null, max_photos: null, default: null, ...f }) as Schemas["IntakeField"];

const opts = (...pairs: [string, string][]) => pairs.map(([value, label]) => ({ value, label, hint: null }));

const cat = (c: Partial<Schemas["Category"]> & Pick<Schemas["Category"], "id" | "name" | "group" | "intake">) =>
  ({ short: c.name, status: "live", skill: "x", pricing_model: "x", measure: null, recurring: false, from_price_pence: 2800, requires: [], icon: "Sprout", sort: 0, ...c }) as Schemas["Category"];

export const catalogue = {
  groups: [
    { id: "outside", name: "Outside", tab: "Outside", sort: 0 },
    { id: "inside", name: "In the home", tab: "Indoors", sort: 1 },
    { id: "help", name: "Help at home", tab: "Help", sort: 2 },
  ],
  categories: [
    cat({
      id: "mowing",
      name: "Lawn mowing",
      group: "outside",
      measure: "lawn",
      recurring: true,
      requires: ["insurance"],
      intake: [
        field({ key: "grassState", type: "choice", label: "How long is the grass right now?", default: "kept", options: [{ value: "kept", label: "Recently cut", hint: "Mown in the last three weeks or so" }, { value: "long", label: "Getting long", hint: null }] }),
        field({ key: "frequency", type: "chips", label: "How often?", default: "fortnightly", options: opts(["weekly", "Weekly"], ["fortnightly", "Every 2 weeks"], ["oneoff", "Just once"]) }),
      ],
    }),
    cat({
      id: "cleaning",
      name: "Regular cleaning",
      group: "inside",
      icon: "Sparkles",
      from_price_pence: 6600,
      intake: [
        field({ key: "bedrooms", type: "number", label: "Bedrooms", default: 3, min: 1, max: 6, unit: "bedrooms", unit1: "bedroom" }),
        field({ key: "extras", type: "multi", label: "Anything extra?", default: [], options: opts(["oven", "Inside the oven"], ["fridge", "Inside the fridge"]) }),
      ],
    }),
    cat({
      id: "flatpack",
      name: "Flat-pack assembly",
      group: "inside",
      icon: "Package",
      intake: [
        field({ key: "items", type: "counts", label: "What needs building?", default: { small: 0, large: 1 }, items: [{ key: "small", label: "Small items", hint: "A bedside table" }, { key: "large", label: "Large items", hint: null }] }),
        field({ key: "notes2", type: "text", label: "Brand or model?", default: "", placeholder: "For example: IKEA PAX" }),
        field({ key: "photos", type: "photos", label: "Photos of the boxes", default: [], max_photos: 4 }),
      ],
    }),
  ],
  document_types: [],
  excluded: [{ id: "gas", name: "Gas boiler work", instead: "a Gas Safe registered engineer", why: "law", sort: 0 }],
};

export const address = {
  line1: "12 Orchard Way",
  line2: "",
  locality: "Hazlemere",
  town: "High Wycombe",
  postcode: "HP15 7QT",
  district: "HP15",
  uprn: "999000000001",
  lat: 51.6541,
  lng: -0.7139,
  label: "12 Orchard Way, Hazlemere, HP15 7QT",
};

export const areaOptions = {
  estimator: "manual_bands_v0",
  confidence: "medium",
  bands: [
    { id: "small", label: "Small", area_m2: 40, comparison: "About a double garage" },
    { id: "medium", label: "Medium", area_m2: 85, comparison: "About a badminton court" },
    { id: "large", label: "Large", area_m2: 190, comparison: "About a singles tennis court" },
    { id: "very_large", label: "Very large", area_m2: 350, comparison: "Bigger than a doubles tennis court" },
  ],
  adjustments: [
    { id: "smaller", label: "Looks smaller", factor: 0.8 },
    { id: "right", label: "About right", factor: 1 },
    { id: "bigger", label: "Looks bigger", factor: 1.2 },
  ],
  tolerance_note: "Your provider sees the same figure and can suggest a different price if it's off.",
};

const split = (price: number, fee: number) => ({ mode: "standard", rate_percent: 15, price_pence: price, fee_pence: fee, provider_pence: price - fee });

export const mowingQuote = {
  id: "q1",
  category_id: "mowing",
  answers: { grassState: "kept", frequency: "fortnightly" },
  measure: { estimator: "manual_bands_v0", area_m2: 190, confidence: "medium", band: "large", adjust: "right", detail: null },
  pricing_version: 1,
  pricing_version_id: "pv1",
  result: { price_pence: 3100, first_pence: null, first_reason: null, mins: 39, first_mins: null, low_pence: 2800, high_pence: 3600, spread: [0.9, 1.15], confidence: "medium", unit: "a visit", note: null, conf_note: "Based on the lawn size you chose, so most providers accept it as it is." },
  fee: split(3100, 465),
  first_fee: null,
  confidence: { level: "medium", bars: 2, label: "Fairly close", note: "Based on the lawn size you chose, so most providers accept it as it is." },
  duration_text: "39 minutes",
  first_duration_text: null,
  created_at: "2026-10-03T09:00:00Z",
};

export const cleaningQuote = {
  ...mowingQuote,
  id: "q2",
  category_id: "cleaning",
  measure: null,
  result: { ...mowingQuote.result, price_pence: 6600, first_pence: 8800, first_reason: "The first clean takes longer while everything is brought up to standard.", unit: "a clean", confidence: "high", conf_note: null },
  fee: split(6600, 990),
  first_fee: split(8800, 1320),
  confidence: { level: "high", bars: 3, label: "Usually close", note: "Most providers accept prices like this as they are." },
  duration_text: "3 hours",
};

export const mike: Schemas["ProviderCard"] = {
  provider_id: "p2",
  short: "Mike R.",
  first_name: "Mike",
  initials: "MR",
  rating_avg: 4.8,
  rating_count: 31,
  miles: 1.4,
  badges: [
    { kind: "identity", label: "ID checked", tone: "ok" },
    { kind: "insured", label: "Insured until Mar 2027", tone: "ok" },
    { kind: "distance", label: "Lives 1.4 miles away", tone: "plain" },
  ],
};

export function request(over: Partial<Schemas["RequestDetail"]> = {}): Schemas["RequestDetail"] {
  return {
    id: "r1",
    ref: "R-2301",
    category_id: "cleaning",
    category_name: "Regular cleaning",
    status: "open",
    guide_pence: 6600,
    first_pence: 8800,
    unit: "a clean",
    area: "Hazlemere",
    district: "HP15",
    created_at: "2026-10-03T09:00:00Z",
    booking_id: null,
    frequency_label: "every 2 weeks",
    timeline: [{ at: "2026-10-03T09:00:00Z", kind: "sent", text: "Sent to checked cleaning providers near HP15", provider: null, offer: null }],
    pending_offers: [],
    booked_with: null,
    booked_price_pence: null,
    booked_via: null,
    demo_simulator: true,
    booked_first_price_pence: null,
    alerted: 3,
    size_text: null,
    notes: "",
    simulating: false,
    ...over,
  } as Schemas["RequestDetail"];
}

export function counter(over: Partial<Schemas["CounterOfferView"]> = {}): Schemas["CounterOfferView"] {
  return {
    offer_id: "o1",
    provider: mike,
    price_pence: 7200,
    first_price_pence: 9600,
    guide_pence: 6600,
    reason_text: "It's a big kitchen.",
    status: "pending",
    created_at: "2026-10-03T09:05:00Z",
    ...over,
  } as Schemas["CounterOfferView"];
}
