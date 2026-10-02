/**
 * OneQuickJob - front-end prototype (design reference for the build)
 * ---------------------------------------------------------------------------
 * One file, three surfaces, three visual versions.
 *
 *   Customer  public quote flow (no account needed to see a price), booking,
 *             account, rating. Designed for the AGENCY structure: the customer
 *             contracts with the named provider and the commission is disclosed.
 *   Provider  mobile web / PWA, entered from a text-message job alert.
 *             Large type and tap targets for the older, casual provider cohort.
 *   Admin     manual-ops console (Phase 1): dispatch via WhatsApp, providers,
 *             pricing calibration, disputes, categories-as-data.
 *
 * Visual versions are design tokens (CSS variables) plus one hero layout per
 * version. Choosing a winner later means deleting two token blocks and two
 * hero components - nothing else changes.
 *
 * For the real build: CATEGORIES and PRICING_MODELS mirror the category-
 * agnostic data model (each category declares its intake schema, a pricing
 * model reference and a provider skill tag). All data here is mock.
 */
import React, { createContext, useContext, useEffect, useRef, useState } from "react";
import {
  AlertTriangle, AppWindow, ArrowLeft, BadgeCheck, Ban, Bell, Car, ChevronRight, CookingPot, Dog, Frame, PiggyBank, Plane,
  HeartHandshake, Receipt, Sparkles, SprayCan, TabletSmartphone, UserPlus, Wrench, Calendar, Camera, Check, Clock, Copy,
  CreditCard, Download, Droplets, FileText, Gauge, Hammer, Home, Info, Layers, LayoutDashboard,
  Lock, MapPin, MessageCircle, Minus, Navigation, Package, PaintRoller, Plus,
  Phone, PoundSterling, Route, Scale, Scissors, Send, ShieldCheck, Smartphone, Sprout, Star,
  Timer, Trash2, User, Users, Wallet, X,
} from "lucide-react";

/* ================================ Config ================================ */

const BRAND = "OneQuickJob"; // product name - change it here only
const LINK = "onequickjob.co.uk"; // short-link domain used in texts
const TAKE_RATE = 0.15; // prototype assumption; research range is 15-25%

const fmt = (n) => {
  const v = Math.round(n * 100) / 100;
  return "£" + v.toLocaleString("en-GB", {
    minimumFractionDigits: Number.isInteger(v) ? 0 : 2,
    maximumFractionDigits: 2,
  });
};
const split = (price) => {
  const provider = Math.round(price * (1 - TAKE_RATE) * 100) / 100;
  return { provider, fee: Math.round((price - provider) * 100) / 100 };
};
const pct = (n) => Math.round(n * 100) + "%";

// Customers a provider brings with them: lower fee, with a floor so card costs are always covered.
const BYOC_RATE = 0.05;
const BYOC_MIN = 1;
const splitOwn = (price) => {
  const fee = Math.max(BYOC_MIN, Math.round(price * BYOC_RATE * 100) / 100);
  return { provider: Math.round((price - fee) * 100) / 100, fee };
};
const initialsOf = (name) => name.trim().split(/\s+/).map((w) => w[0] || "").join("").slice(0, 2).toUpperCase();
const firstName = (s) => (s || "").trim().split(/\s+/)[0];

/* ======================= Categories (data, not code) ======================= */
/*
 * Each live category declares:
 *   group          which tab it sits under on the customer quote starter
 *   skill          provider skill tag used for matching
 *   pricingModel   reference into PRICING_MODELS, plus pricingParams
 *   measure        "lawn" if the quote flow includes the LIDAR lawn step
 *   requires       documents a provider must hold to take this category
 *   intake         the questions the customer answers (rendered generically)
 *
 * Adding a job type = adding a record here. Only a genuinely new way of
 * pricing needs a new function in PRICING_MODELS.
 */
const GROUPS = [
  { id: "outside", name: "Outside" },
  { id: "inside", name: "In the home" },
  { id: "help", name: "Help at home" },
];

const DOCS = {
  insurance: "Public liability insurance",
  waste_carrier: "Waste carrier registration",
  ladder_cover: "Insurance that covers ladder work",
  dbs_basic: "Basic DBS check",
  pet_cover: "Insurance that covers pet care",
};

const yesNo = (yes, no) => [{ value: "yes", label: yes }, { value: "no", label: no }];
const WASTE_CHIPS = [{ value: "takeaway", label: "Take it away" }, { value: "bin", label: "Leave it in my bin or bags" }];

const CATEGORIES = [
  /* ----- Outside ----- */
  {
    id: "mowing", name: "Lawn mowing", short: "Mowing", group: "outside", status: "live",
    skill: "garden.mowing", pricingModel: "lawn_area_v1", measure: "lawn",
    recurring: true, fromPrice: 28, requires: ["insurance"],
    intake: [
      { key: "grassState", type: "choice", label: "How long is the grass right now?", default: "kept",
        options: [
          { value: "kept", label: "Recently cut", hint: "Mown in the last three weeks or so" },
          { value: "long", label: "Getting long", hint: "About three to six weeks since the last cut" },
          { value: "overgrown", label: "Overgrown", hint: "Ankle-high or more" },
        ] },
      { key: "waste", type: "choice", label: "What should happen to the clippings?", default: "takeaway",
        options: [
          { value: "takeaway", label: "Take them away", hint: "Adds a small disposal charge" },
          { value: "bin", label: "Put them in my garden waste bin" },
          { value: "compost", label: "Leave them on my compost heap" },
        ] },
      { key: "access", type: "chips", label: "How do they get to the back garden?", default: "gate",
        options: [{ value: "gate", label: "Side gate" }, { value: "house", label: "Through the house" }, { value: "lane", label: "Rear access" }] },
      { key: "frequency", type: "chips", label: "How often?", default: "fortnightly",
        options: [{ value: "weekly", label: "Weekly" }, { value: "fortnightly", label: "Every 2 weeks" }, { value: "threeweekly", label: "Every 3 weeks" }, { value: "oneoff", label: "Just once" }] },
    ],
  },
  {
    id: "hedges", name: "Hedge trimming", short: "Hedges", group: "outside", status: "live",
    skill: "garden.hedges", pricingModel: "hedge_length_v1", recurring: false, fromPrice: 40, requires: ["insurance"],
    intake: [
      { key: "length", type: "number", label: "Roughly how much hedge is there?", hint: "A fence panel is about 1.8 m wide, if that helps.", unit: "m", min: 2, max: 80, step: 1, default: 15 },
      { key: "height", type: "choice", label: "How tall is it?", default: "head",
        options: [{ value: "waist", label: "Below waist height" }, { value: "head", label: "Around head height" }, { value: "above", label: "Taller than a person", hint: "Needs a ladder or platform" }] },
      { key: "sides", type: "chips", label: "Which parts need cutting?", default: "one",
        options: [{ value: "one", label: "My side only" }, { value: "both", label: "Both sides and the top" }] },
      { key: "waste", type: "chips", label: "Cuttings", default: "takeaway", options: WASTE_CHIPS },
    ],
  },
  {
    id: "clearance", name: "Garden clearance", short: "Clearance", group: "outside", status: "live",
    skill: "garden.clearance", pricingModel: "photo_review_v1", recurring: false, fromPrice: 65, requires: ["insurance", "waste_carrier"],
    intake: [
      { key: "photos", type: "photos", label: "Add a few photos of the area", hint: "For clearance, photos matter more than measurements. They're what providers price from.", default: 2 },
      { key: "volume", type: "choice", label: "Roughly how much needs to go?", default: "boot",
        options: [
          { value: "bags", label: "A few bags", hint: "Up to five garden sacks" },
          { value: "boot", label: "A car boot's worth" },
          { value: "smallvan", label: "A small van load" },
          { value: "large", label: "More than that", hint: "A provider may want to see it first" },
        ] },
      { key: "waste", type: "chips", label: "Waste", default: "takeaway",
        options: [{ value: "takeaway", label: "Take it all away" }, { value: "bags", label: "Bag it up and I'll dispose of it" }] },
    ],
  },
  {
    id: "jetwash", name: "Jet washing", short: "Jet wash", group: "outside", status: "live",
    skill: "exterior.jetwash", pricingModel: "area_rate_v1", recurring: false, fromPrice: 60, requires: ["insurance"],
    pricingParams: { rates: { patio: 3.5, driveway: 3, decking: 4, paths: 3.5 }, resand: 1.5, min: 60, minsPerM2: 1.6 },
    intake: [
      { key: "surface", type: "chips", label: "What needs cleaning?", default: "patio",
        options: [{ value: "patio", label: "Patio" }, { value: "driveway", label: "Driveway" }, { value: "decking", label: "Decking" }, { value: "paths", label: "Paths" }] },
      { key: "area", type: "number", label: "Roughly how big is it?", hint: "A typical double driveway is about 30 m².", unit: "m²", min: 5, max: 300, step: 5, default: 25 },
      { key: "resand", type: "chips", label: "Re-sand the joints afterwards?", hint: "Worth it for block paving.", default: "no", options: yesNo("Yes please", "No thanks") },
    ],
  },
  {
    id: "gutters", name: "Gutter clearing", short: "Gutters", group: "outside", status: "live",
    skill: "exterior.gutters", pricingModel: "size_base_v1", recurring: false, fromPrice: 55, requires: ["insurance", "ladder_cover"],
    pricingParams: { baseKey: "house", base: { bungalow: 55, semi: 70, detached: 95, three: 140 }, mins: { bungalow: 45, semi: 60, detached: 90, three: 150 },
      addIf: { conservatory: { price: 25, mins: 20 }, downpipes: { price: 15, mins: 15 } } },
    intake: [
      { key: "house", type: "choice", label: "What kind of house is it?", default: "semi",
        options: [
          { value: "bungalow", label: "Bungalow" },
          { value: "semi", label: "Two storeys, semi or terraced" },
          { value: "detached", label: "Two storeys, detached" },
          { value: "three", label: "Three storeys", hint: "Needs specialist equipment. A provider will check first." },
        ] },
      { key: "conservatory", type: "chips", label: "Conservatory gutters too?", default: "no", options: yesNo("Yes", "No") },
      { key: "downpipes", type: "chips", label: "Check the downpipes are clear?", default: "yes", options: yesNo("Yes", "No") },
    ],
  },
  {
    id: "windows", name: "Window cleaning", short: "Windows", group: "outside", status: "live",
    skill: "exterior.windows", pricingModel: "window_round_v1", recurring: true, fromPrice: 15, requires: ["insurance", "ladder_cover"],
    pricingParams: { base: { small: 15, semi: 22, detached: 30, large: 42 }, mins: { small: 20, semi: 30, detached: 40, large: 60 }, conservatory: 12 },
    intake: [
      { key: "size", type: "choice", label: "What size is the house?", default: "semi",
        options: [{ value: "small", label: "Flat or small terrace" }, { value: "semi", label: "Three-bed semi" }, { value: "detached", label: "Four-bed detached" }, { value: "large", label: "Larger than that" }] },
      { key: "sides", type: "chips", label: "Which sides?", default: "outside", options: [{ value: "outside", label: "Outside only" }, { value: "both", label: "Inside and outside" }] },
      { key: "conservatory", type: "chips", label: "Conservatory too?", default: "no", options: yesNo("Yes", "No") },
      { key: "frequency", type: "chips", label: "How often?", default: "fourweekly",
        options: [{ value: "fourweekly", label: "Every 4 weeks" }, { value: "eightweekly", label: "Every 8 weeks" }, { value: "oneoff", label: "Just once" }] },
    ],
  },

  /* ----- In the home ----- */
  {
    id: "cleaning", name: "Regular cleaning", short: "Cleaning", group: "inside", status: "live",
    skill: "home.cleaning", pricingModel: "rooms_hours_v1", recurring: true, fromPrice: 44, requires: ["insurance", "dbs_basic"],
    pricingParams: { rate: 22, baseHours: 1, perBed: 0.5, perBath: 0.5, minHours: 2, suppliesFee: 3,
      extras: { oven: 1, fridge: 0.5, windows: 0.5, ironing: 1 } },
    intake: [
      { key: "bedrooms", type: "number", label: "How many bedrooms?", unit: "bedrooms", unit1: "bedroom", min: 1, max: 6, step: 1, default: 3 },
      { key: "bathrooms", type: "number", label: "And bathrooms?", hint: "Count toilets and en-suites too.", unit: "bathrooms", unit1: "bathroom", min: 1, max: 5, step: 1, default: 1 },
      { key: "frequency", type: "chips", label: "How often?", default: "fortnightly",
        options: [{ value: "weekly", label: "Weekly" }, { value: "fortnightly", label: "Every 2 weeks" }, { value: "oneoff", label: "Just once" }] },
      { key: "extras", type: "multi", label: "Anything extra?", default: [],
        options: [{ value: "oven", label: "Inside the oven" }, { value: "fridge", label: "Inside the fridge" }, { value: "windows", label: "Inside windows" }, { value: "ironing", label: "An hour of ironing" }] },
      { key: "supplies", type: "chips", label: "Cleaning products and equipment", default: "mine",
        options: [{ value: "mine", label: "Use mine" }, { value: "bring", label: "Bring their own" }] },
    ],
  },
  {
    id: "deepclean", name: "Deep clean", short: "Deep clean", group: "inside", status: "live",
    skill: "home.deepclean", pricingModel: "rooms_hours_v1", recurring: false, fromPrice: 72, requires: ["insurance", "dbs_basic"],
    pricingParams: { rate: 24, baseHours: 2, perBed: 1.5, perBath: 1.25, minHours: 3, furnishedMult: 1.15,
      typeMult: { deep: 1, eot: 1.25, builders: 1.45 }, extras: { oven: 1.5, fridge: 0.5, cupboards: 1, windows: 1 }, confidence: "medium" },
    intake: [
      { key: "type", type: "choice", label: "What kind of clean?", default: "deep",
        options: [
          { value: "deep", label: "A top-to-bottom deep clean" },
          { value: "eot", label: "End of tenancy", hint: "Aimed at getting the deposit back" },
          { value: "builders", label: "After building or decorating work" },
        ] },
      { key: "bedrooms", type: "number", label: "How many bedrooms?", unit: "bedrooms", unit1: "bedroom", min: 1, max: 6, step: 1, default: 2 },
      { key: "bathrooms", type: "number", label: "And bathrooms?", unit: "bathrooms", unit1: "bathroom", min: 1, max: 5, step: 1, default: 1 },
      { key: "furnished", type: "chips", label: "Is the place furnished?", default: "furnished", options: [{ value: "furnished", label: "Furnished" }, { value: "empty", label: "Empty" }] },
      { key: "extras", type: "multi", label: "Anything extra?", default: ["oven"],
        options: [{ value: "oven", label: "Oven" }, { value: "fridge", label: "Fridge" }, { value: "cupboards", label: "Inside cupboards" }, { value: "windows", label: "Inside windows" }] },
    ],
  },
  {
    id: "oven", name: "Oven cleaning", short: "Oven", group: "inside", status: "live",
    skill: "home.oven", pricingModel: "size_base_v1", recurring: false, fromPrice: 60, requires: ["insurance", "dbs_basic"],
    pricingParams: { baseKey: "ovenType", base: { single: 60, double: 80, range: 110 }, mins: { single: 120, double: 160, range: 210 },
      extras: { hob: { price: 10, mins: 15 }, hood: { price: 15, mins: 20 }, microwave: { price: 10, mins: 15 } }, confidence: "high" },
    intake: [
      { key: "ovenType", type: "choice", label: "What kind of oven?", default: "single",
        options: [{ value: "single", label: "Single oven" }, { value: "double", label: "Double oven" }, { value: "range", label: "Range cooker" }] },
      { key: "extras", type: "multi", label: "Anything else in the kitchen?", default: ["hob"],
        options: [{ value: "hob", label: "Hob" }, { value: "hood", label: "Extractor hood" }, { value: "microwave", label: "Microwave" }] },
    ],
  },
  {
    id: "decorating", name: "Painting and decorating", short: "Decorating", group: "inside", status: "live",
    skill: "home.decorating", pricingModel: "decorating_v1", recurring: false, fromPrice: 90, requires: ["insurance", "dbs_basic"],
    pricingParams: { rate: 26, sizeHours: { small: 3.5, average: 5, large: 7.5 } },
    intake: [
      { key: "rooms", type: "number", label: "How many rooms?", unit: "rooms", unit1: "room", min: 1, max: 8, step: 1, default: 1 },
      { key: "size", type: "choice", label: "How big is a typical room?", default: "average",
        options: [{ value: "small", label: "Small", hint: "A box room or small bathroom" }, { value: "average", label: "Average", hint: "A double bedroom or living room" }, { value: "large", label: "Large or open-plan" }] },
      { key: "parts", type: "multi", label: "What needs painting?", default: ["walls", "ceiling"],
        options: [{ value: "walls", label: "Walls" }, { value: "ceiling", label: "Ceiling" }, { value: "woodwork", label: "Skirting, doors and frames" }] },
      { key: "condition", type: "chips", label: "What state are the walls in?", default: "good",
        options: [{ value: "good", label: "Good, just tired" }, { value: "prep", label: "Cracks or holes to fill" }] },
      { key: "paint", type: "chips", label: "Paint", default: "mine",
        options: [{ value: "mine", label: "I'll buy it" }, { value: "provider", label: "Provider buys it, charged at cost" }] },
    ],
  },
  {
    id: "flatpack", name: "Flat-pack assembly", short: "Flat-pack", group: "inside", status: "live",
    skill: "home.flatpack", pricingModel: "counts_v1", recurring: false, fromPrice: 35, requires: ["insurance", "dbs_basic"],
    pricingParams: { min: 35, each: { small: { price: 20, mins: 30 }, medium: { price: 40, mins: 60 }, large: { price: 75, mins: 120 } },
      addIf: { anchor: { price: 10, mins: 15 }, packaging: { price: 8, mins: 10 } } },
    intake: [
      { key: "items", type: "counts", label: "What needs putting together?", default: { small: 0, medium: 1, large: 1 },
        items: [
          { key: "small", label: "Small", hint: "Bedside table, small shelf unit" },
          { key: "medium", label: "Medium", hint: "Chest of drawers, desk, bed" },
          { key: "large", label: "Large", hint: "Wardrobe, tall bookcase" },
        ] },
      { key: "anchor", type: "chips", label: "Fix tall furniture to the wall?", hint: "Recommended, especially with children at home.", default: "yes", options: yesNo("Yes please", "No thanks") },
      { key: "packaging", type: "chips", label: "Take the packaging away?", default: "yes", options: yesNo("Yes please", "No, I'll recycle it") },
    ],
  },
  {
    id: "mounting", name: "Putting things up", short: "Putting up", group: "inside", status: "live",
    skill: "home.mounting", pricingModel: "counts_v1", recurring: false, fromPrice: 40, requires: ["insurance", "dbs_basic"],
    pricingParams: { min: 40, unsureKey: "wall", each: { tv: { price: 60, mins: 60 }, shelves: { price: 25, mins: 30 }, pictures: { price: 12, mins: 15 }, curtains: { price: 30, mins: 40 } },
      note: "We don't move sockets or run new wiring. That's electrical work." },
    intake: [
      { key: "items", type: "counts", label: "What needs putting up?", default: { tv: 1, shelves: 2, pictures: 0, curtains: 0 },
        items: [
          { key: "tv", label: "TV on a wall bracket", hint: "Up to 55 inches" },
          { key: "shelves", label: "Shelves" },
          { key: "pictures", label: "Pictures or mirrors" },
          { key: "curtains", label: "Curtain poles or blinds" },
        ] },
      { key: "wall", type: "chips", label: "What are the walls made of?", default: "unsure",
        options: [{ value: "plasterboard", label: "Plasterboard" }, { value: "brick", label: "Brick or block" }, { value: "unsure", label: "Not sure" }] },
    ],
  },
  {
    id: "repairs", name: "Small repairs", short: "Repairs", group: "inside", status: "live",
    skill: "home.repairs", pricingModel: "hours_estimate_v1", recurring: false, fromPrice: 35, requires: ["insurance", "dbs_basic"],
    pricingParams: { key: "size", rate: 30, min: 35, hours: { quick: 1, couple: 2, half: 4, unsure: 2 } },
    intake: [
      { key: "description", type: "text", label: "What needs fixing?", placeholder: "For example: a sticking back door, a dripping tap washer and a loose kitchen cupboard hinge.", default: "" },
      { key: "photos", type: "photos", label: "Add photos if you can", hint: "They help providers price it properly.", default: 1 },
      { key: "size", type: "choice", label: "How long do you think it'll take?", default: "couple",
        options: [{ value: "quick", label: "Under an hour" }, { value: "couple", label: "An hour or two" }, { value: "half", label: "About half a day" }, { value: "unsure", label: "No idea" }] },
    ],
  },

  /* ----- Help at home ----- */
  {
    id: "techhelp", name: "Tech help", short: "Tech help", group: "help", status: "live",
    skill: "help.tech", pricingModel: "hours_estimate_v1", recurring: false, fromPrice: 25, requires: ["insurance", "dbs_basic"],
    pricingParams: { key: "length", rate: 25, min: 25, hours: { one: 1, two: 2 }, confidence: "high" },
    intake: [
      { key: "topics", type: "multi", label: "What would help?", default: ["phone"],
        options: [
          { value: "phone", label: "Setting up a phone or tablet" },
          { value: "calls", label: "Video calls with family" },
          { value: "wifi", label: "Wi-Fi or a printer" },
          { value: "scams", label: "Staying safe from scams" },
          { value: "tv", label: "A smart TV" },
        ] },
      { key: "length", type: "chips", label: "How long?", default: "one", options: [{ value: "one", label: "An hour" }, { value: "two", label: "Two hours" }] },
      { key: "forWhom", type: "chips", label: "Who is it for?", default: "me", options: [{ value: "me", label: "Me" }, { value: "relative", label: "A relative" }] },
    ],
  },
  {
    id: "dogwalking", name: "Dog walking", short: "Dog walks", group: "help", status: "live",
    skill: "help.dogs", pricingModel: "per_visit_v1", recurring: true, fromPrice: 12, requires: ["insurance", "dbs_basic", "pet_cover"],
    pricingParams: { base: { half: 12, hour: 16 }, extraDog: 5 },
    intake: [
      { key: "dogs", type: "number", label: "How many dogs?", unit: "dogs", unit1: "dog", min: 1, max: 3, step: 1, default: 1 },
      { key: "length", type: "chips", label: "How long a walk?", default: "hour", options: [{ value: "half", label: "30 minutes" }, { value: "hour", label: "An hour" }] },
      { key: "frequency", type: "chips", label: "How often?", default: "weekdays",
        options: [{ value: "weekdays", label: "Every weekday" }, { value: "someweekdays", label: "A few days a week" }, { value: "oneoff", label: "Just once" }] },
      { key: "keys", type: "chips", label: "Getting in", hint: "Anyone holding a key has a basic DBS check.", default: "home",
        options: [{ value: "home", label: "Someone will be in" }, { value: "key", label: "They'll need a key" }] },
    ],
  },
];

// Jobs we deliberately never list, and who to use instead.
const EXCLUDED = [
  { name: "Gas and boilers", instead: "a Gas Safe registered engineer", why: "Legally restricted to registered engineers" },
  { name: "Electrics beyond bulbs and plugs", instead: "a registered electrician, for example NICEIC or NAPIT", why: "Building Regulations and safety" },
  { name: "Roofs and chimneys", instead: "a roofer", why: "Work at height beyond ladder cover" },
  { name: "Building and structural work", instead: "a builder", why: "Building Regulations sign-off" },
  { name: "Tree felling and big tree work", instead: "a qualified tree surgeon", why: "Chainsaw and height risk" },
  { name: "Anything involving asbestos", instead: "a specialist asbestos contractor", why: "Regulated, serious health risk" },
  { name: "Personal care", instead: "a CQC-registered care provider", why: "CQC-regulated activity" },
  { name: "Childcare and babysitting", instead: "an Ofsted-registered childminder or nanny", why: "Safeguarding and registration" },
  { name: "Lifts and driving people", instead: "a licensed taxi or private hire firm", why: "Needs a private hire licence" },
  { name: "Pest control", instead: "a pest control professional", why: "Some products are restricted to certified users" },
];

const CAT_ICONS = {
  mowing: Sprout, hedges: Scissors, clearance: Trash2, jetwash: Droplets, gutters: Home, windows: AppWindow,
  cleaning: Sparkles, deepclean: SprayCan, oven: CookingPot, decorating: PaintRoller, flatpack: Package,
  mounting: Frame, repairs: Wrench, techhelp: TabletSmartphone, dogwalking: Dog,
};
const catById = (id) => CATEGORIES.find((c) => c.id === id);
const defaultsFor = (cat) => Object.fromEntries(cat.intake.map((f) => [f.key, f.default]));
const optionLabel = (cat, key, value) =>
  cat.intake?.find((f) => f.key === key)?.options?.find((o) => o.value === value)?.label;
const isRecurring = (cat, answers) => !!cat.recurring && !!answers?.frequency && answers.frequency !== "oneoff";

const fmtDuration = (mins) => {
  if (mins < 90) return `${Math.round(mins)} minutes`;
  const h = Math.round((mins / 60) * 2) / 2;
  return `${Math.floor(h)}${h % 1 ? "½" : ""} hours`;
};

/* ============================ Pricing models ============================ */
/*
 * Each takes (answers, params) and returns
 *   { price, first?, firstReason?, mins, spread:[lo,hi], confidence, unit, note?, confNote? }.
 * Coefficients are placeholders. The calibration loop (admin > Pricing)
 * replaces them with values fitted from recorded completion times.
 */
const HOURLY = 45; // customer-facing £/hour assumption for garden work

const PRICING_MODELS = {
  lawn_area_v1: ({ area, grassState, waste, frequency }) => {
    const growth = { kept: 1, long: 1.35, overgrown: 1.9 }[grassState] ?? 1;
    const base = 12 + area * 0.11;
    const wasteMins = waste === "takeaway" ? 6 : 0;
    const disposal = waste === "takeaway" ? 4 : 0;
    const discount = { weekly: 0.12, fortnightly: 0.08, threeweekly: 0.05, oneoff: 0 }[frequency] ?? 0;
    const recurring = frequency !== "oneoff";
    const routine = Math.round(base + wasteMins);
    const firstMins = Math.round(base * growth + wasteMins);
    const cost = (m, d) => Math.max(28, Math.round(((m / 60) * HOURLY + disposal) * (1 - d)));
    const common = { spread: [0.9, 1.15], confidence: "high", confNote: "Measured from survey data, so most providers accept it as it is." };
    if (recurring && growth > 1) {
      return { ...common, price: cost(routine, discount), first: cost(firstMins, 0), mins: routine, firstMins,
        firstReason: "The grass needs extra time to get back under control.", unit: "a visit" };
    }
    return { ...common, price: cost(firstMins, recurring ? discount : 0), mins: firstMins, unit: recurring ? "a visit" : "one-off" };
  },

  hedge_length_v1: ({ length, height, sides, waste }) => {
    const perM = { waist: 2, head: 3.2, above: 5.5 }[height] ?? 3.2;
    const mins = Math.round(10 + length * perM * (sides === "both" ? 1.8 : 1));
    const disposal = waste === "takeaway" ? 8 + length * 0.6 : 0;
    return { price: Math.max(40, Math.round((mins / 60) * HOURLY + disposal)), mins,
      spread: [0.85, 1.25], confidence: "medium", confNote: "Hedges vary with thickness, so some providers adjust the price.", unit: "one-off" };
  },

  photo_review_v1: ({ volume, waste }) => {
    const base = { bags: 65, boot: 110, smallvan: 190, large: 320 }[volume] ?? 110;
    const mins = { bags: 90, boot: 150, smallvan: 240, large: 360 }[volume] ?? 150;
    return { price: Math.round(waste === "bags" ? base * 0.8 : base), mins, spread: [0.75, 1.4], confidence: "low", unit: "one-off" };
  },

  area_rate_v1: ({ surface, area, resand }, p) => {
    const extra = resand === "yes" ? p.resand : 0;
    return { price: Math.max(p.min, Math.round(area * ((p.rates[surface] ?? 3.5) + extra))),
      mins: Math.round((30 + area * p.minsPerM2) * (resand === "yes" ? 1.3 : 1)),
      spread: [0.85, 1.2], confidence: "medium", unit: "one-off" };
  },

  size_base_v1: (a, p) => {
    let price = p.base[a[p.baseKey]] ?? 0;
    let mins = p.mins[a[p.baseKey]] ?? 60;
    for (const [k, v] of Object.entries(p.addIf || {})) if (a[k] === "yes") { price += v.price; mins += v.mins; }
    for (const e of a.extras || []) { price += p.extras?.[e]?.price || 0; mins += p.extras?.[e]?.mins || 0; }
    return { price: Math.round(price), mins, spread: [0.9, 1.2], confidence: p.confidence || "medium", unit: "one-off" };
  },

  window_round_v1: ({ size, sides, conservatory, frequency }, p) => {
    const both = sides === "both" ? 1.8 : 1;
    const price = Math.round(p.base[size] * both + (conservatory === "yes" ? p.conservatory : 0));
    const mins = Math.round(p.mins[size] * both + (conservatory === "yes" ? 20 : 0));
    if (frequency === "oneoff") {
      return { price: Math.round(price * 1.5), mins: Math.round(mins * 1.5), spread: [0.9, 1.15], confidence: "high", unit: "one-off" };
    }
    return { price, first: Math.round(price * 1.5), mins, firstMins: Math.round(mins * 1.5),
      firstReason: "First cleans take longer because of the build-up on the glass and frames.",
      spread: [0.9, 1.15], confidence: "high", unit: "a clean" };
  },

  rooms_hours_v1: (a, p) => {
    let hours = p.baseHours + (a.bedrooms ?? 2) * p.perBed + (a.bathrooms ?? 1) * p.perBath;
    hours *= (p.typeMult?.[a.type] ?? 1) * (a.furnished === "furnished" ? p.furnishedMult ?? 1 : 1);
    for (const e of a.extras || []) hours += p.extras?.[e] ?? 0;
    hours = Math.max(p.minHours, Math.round(hours * 2) / 2);
    const supplies = a.supplies === "bring" ? p.suppliesFee ?? 0 : 0;
    const price = Math.round(hours * p.rate + supplies);
    if (a.frequency && a.frequency !== "oneoff") {
      const fh = Math.round(hours * 1.4 * 2) / 2;
      return { price, first: Math.round(fh * p.rate + supplies), mins: hours * 60, firstMins: fh * 60,
        firstReason: "The first clean takes longer while everything is brought up to standard.",
        spread: [0.9, 1.15], confidence: "high", unit: "a clean" };
    }
    return { price, mins: hours * 60, spread: [0.85, 1.2], confidence: p.confidence || "medium", unit: "one-off" };
  },

  decorating_v1: ({ rooms, size, parts, condition, paint }, p) => {
    const per = p.sizeHours[size] ?? 5;
    const chosen = parts && parts.length ? parts : ["walls"];
    let hours = (chosen.includes("walls") ? per : 0) + (chosen.includes("ceiling") ? per * 0.35 : 0) + (chosen.includes("woodwork") ? per * 0.45 : 0);
    hours = Math.round(hours * rooms * (condition === "prep" ? 1.25 : 1) * 2) / 2;
    return { price: Math.round(hours * p.rate), mins: hours * 60, spread: [0.85, 1.25], confidence: "medium", unit: "one-off",
      note: paint === "provider" ? "Paint isn't included. It's charged at cost, with the receipt." : "Labour only. You buy the paint." };
  },

  counts_v1: (a, p) => {
    let price = 0, mins = 0;
    for (const [k, n] of Object.entries(a.items || {})) { price += (p.each[k]?.price || 0) * n; mins += (p.each[k]?.mins || 0) * n; }
    for (const [k, v] of Object.entries(p.addIf || {})) if (a[k] === "yes") { price += v.price; mins += v.mins; }
    const unsure = p.unsureKey && a[p.unsureKey] === "unsure";
    return { price: Math.max(p.min, Math.round(price)), mins: Math.max(30, mins), spread: unsure ? [0.85, 1.3] : [0.9, 1.2],
      confidence: unsure ? "medium" : "high", unit: "one-off", note: p.note };
  },

  hours_estimate_v1: (a, p) => {
    const choice = a[p.key];
    const h = p.hours[choice] ?? 2;
    const unsure = choice === "unsure";
    return { price: Math.max(p.min, Math.round(h * p.rate)), mins: h * 60, spread: unsure ? [0.7, 1.6] : [0.85, 1.25],
      confidence: unsure ? "low" : p.confidence || "medium", unit: "one-off" };
  },

  per_visit_v1: ({ dogs, length, frequency }, p) => ({
    price: Math.round(p.base[length] + ((dogs ?? 1) - 1) * p.extraDog), mins: length === "half" ? 30 : 60,
    spread: [0.9, 1.15], confidence: "high", unit: frequency === "oneoff" ? "one-off" : "a walk",
  }),
};
// Only the lawn step supplies a measured area; other categories use their own answers.
const estimateFor = (cat, answers, area) =>
  PRICING_MODELS[cat.pricingModel]({ ...answers, ...(cat.measure === "lawn" ? { area } : {}) }, cat.pricingParams || {});

const LAWNS = { front: 48, back: 138 }; // m², from EA LIDAR (mock)
const AREA_ADJ = { smaller: 0.8, right: 1, bigger: 1.2 };
const lawnArea = (q) =>
  Math.round(((q.lawns.front ? LAWNS.front : 0) + (q.lawns.back ? LAWNS.back : 0)) * AREA_ADJ[q.areaAdj]);

const initialQuote = {
  categoryId: "mowing",
  address: "12 Orchard Way, Hazlemere, HP15 7QT",
  lawns: { front: true, back: true },
  areaAdj: "right",
  answers: Object.fromEntries(CATEGORIES.map((c) => [c.id, defaultsFor(c)])),
  notes: "",
  when: { days: "weekdays", time: "morning" },
  contact: { name: "Sarah Whitfield", phone: "07700 900123", email: "sarah.w@example.com" },
  booking: null,
  accountTab: "visits",
};

/* ================================ Mock data ================================ */

const PROVIDERS = [
  { id: "dave", name: "Dave Hughes", short: "Dave H.", initials: "DH", area: "Hazlemere", district: "HP15",
    skills: ["mowing", "hedges", "jetwash", "gutters"], docs: ["insurance", "waste_carrier", "ladder_cover"],
    rating: 4.9, reviews: 38, jobs30: 22, accept: 0.72, miles: 1.2, insurance: { status: "ok", expires: "14 Mar 2027" }, hmrc: "ok", status: "Active" },
  { id: "mike", name: "Mike Reynolds", short: "Mike R.", initials: "MR", area: "Widmer End", district: "HP15",
    skills: ["mowing", "clearance", "jetwash", "windows"], docs: ["insurance", "waste_carrier", "ladder_cover"],
    rating: 4.7, reviews: 21, jobs30: 14, accept: 0.58, miles: 1.9, insurance: { status: "ok", expires: "2 Jan 2027" }, hmrc: "ok", status: "Active" },
  { id: "lorna", name: "Lorna Baines", short: "Lorna B.", initials: "LB", area: "Terriers", district: "HP13",
    skills: ["cleaning", "deepclean", "oven"], docs: ["insurance", "dbs_basic"],
    rating: 4.9, reviews: 44, jobs30: 31, accept: 0.8, miles: 1.6, insurance: { status: "ok", expires: "21 Feb 2027" }, hmrc: "ok", status: "Active" },
  { id: "kasia", name: "Kasia Nowak", short: "Kasia N.", initials: "KN", area: "Booker", district: "HP12",
    skills: ["cleaning", "deepclean"], docs: ["insurance", "dbs_basic"],
    rating: 4.8, reviews: 19, jobs30: 17, accept: 0.66, miles: 3.8, insurance: { status: "ok", expires: "5 May 2027" }, hmrc: "ok", status: "Active" },
  { id: "steve", name: "Steve Collins", short: "Steve C.", initials: "SC", area: "Cressex", district: "HP12",
    skills: ["flatpack", "mounting", "repairs", "decorating"], docs: ["insurance", "dbs_basic"],
    rating: 4.9, reviews: 27, jobs30: 15, accept: 0.7, miles: 3.1, insurance: { status: "ok", expires: "30 Sep 2027" }, hmrc: "ok", status: "Active" },
  { id: "ray", name: "Ray Mills", short: "Ray M.", initials: "RM", area: "Holmer Green", district: "HP15",
    skills: ["flatpack", "repairs", "techhelp", "decorating", "mounting"], docs: ["insurance", "dbs_basic"],
    rating: 5.0, reviews: 14, jobs30: 9, accept: 0.74, miles: 2.2, insurance: { status: "ok", expires: "12 Jan 2027" }, hmrc: "ok", status: "Active" },
  { id: "hannah", name: "Hannah Reid", short: "Hannah R.", initials: "HR", area: "Penn", district: "HP10",
    skills: ["dogwalking", "techhelp", "oven"], docs: ["insurance", "dbs_basic", "pet_cover"],
    rating: 4.8, reviews: 23, jobs30: 26, accept: 0.83, miles: 3.4, insurance: { status: "ok", expires: "1 Apr 2027" }, hmrc: "ok", status: "Active" },
  { id: "sue", name: "Sue Palmer", short: "Sue P.", initials: "SP", area: "Penn", district: "HP10",
    skills: ["hedges", "mowing", "windows", "dogwalking", "gutters"], docs: ["insurance", "ladder_cover", "dbs_basic", "pet_cover"],
    rating: 5.0, reviews: 17, jobs30: 11, accept: 0.81, miles: 3.4, insurance: { status: "ok", expires: "30 Jun 2027" }, hmrc: "ok", status: "Active" },
  { id: "gary", name: "Gary Tomlinson", short: "Gary T.", initials: "GT", area: "Booker", district: "HP12",
    skills: ["clearance", "hedges", "repairs"], docs: ["insurance", "waste_carrier", "dbs_basic"],
    rating: 4.6, reviews: 12, jobs30: 8, accept: 0.64, miles: 4.1, insurance: { status: "ok", expires: "19 Nov 2026" }, hmrc: "ok", status: "Active" },
  { id: "alan", name: "Alan Pryce", short: "Alan P.", initials: "AP", area: "Marlow", district: "SL7",
    skills: ["mowing"], docs: ["insurance"],
    rating: 4.8, reviews: 26, jobs30: 16, accept: 0.69, miles: 5.2, insurance: { status: "warn", expires: "2 Oct 2026" }, hmrc: "ok", status: "Active" },
  { id: "jan", name: "Jan Kowalski", short: "Jan K.", initials: "JK", area: "Downley", district: "HP13",
    skills: ["mowing", "hedges"], docs: ["insurance"],
    rating: 4.9, reviews: 9, jobs30: 6, accept: 0.77, miles: 2.6, insurance: { status: "ok", expires: "8 Aug 2027" }, hmrc: "missing", status: "Payouts paused" },
  { id: "ken", name: "Ken Ashworth", short: "Ken A.", initials: "KA", area: "Beaconsfield", district: "HP9",
    skills: ["mowing"], docs: [],
    rating: null, reviews: 0, jobs30: 0, accept: null, miles: 6.0, insurance: { status: "missing" }, hmrc: "missing", status: "Signing up" },
];
// Active providers who do a category, best-rated first.
const providersFor = (catId) => PROVIDERS
  .filter((p) => p.status === "Active" && p.skills.includes(catId))
  .sort((a, b) => (b.rating || 0) - (a.rating || 0));
const providerById = (id) => PROVIDERS.find((p) => p.id === id) || PROVIDERS[0];

const PROVIDER_OFFERS = [
  { id: "8K2Q", cat: "mowing", where: "Hazlemere, HP15", miles: 1.2, mins: 38, guide: 30,
    freq: "Every 2 weeks", posted: "4 min ago", route: "0.4 miles from your 9:00 on Tuesday",
    customer: { initials: "SW", name: "Sarah W.", meta: "3 past bookings, pays by card" },
    note: "The side gate sticks, so please close it behind you. The dog's out.",
    facts: [["Lawn", "About 186 m²"], ["Grass", "Recently cut"], ["Clippings", "Take away"],
      ["Access", "Side gate"], ["When", "Weekday mornings"], ["Estimate", "About 38 min"]] },
  { id: "8K1M", cat: "hedges", where: "Widmer End, HP15", miles: 1.9, mins: 58, guide: 61,
    freq: "One-off", posted: "1 hr ago", route: "Same road as your Thursday job",
    customer: { initials: "RB", name: "Robert B.", meta: "First booking, pays by card" },
    facts: [["Hedge", "About 15 m"], ["Height", "Around head height"], ["Sides", "Customer's side only"],
      ["Cuttings", "Take away"], ["When", "Any day"], ["Estimate", "About 58 min"]] },
  { id: "8JZP", cat: "jetwash", where: "Tylers Green, HP10", miles: 3.1, mins: 70, guide: 88,
    freq: "One-off", posted: "3 hr ago", route: null,
    customer: { initials: "AK", name: "Anita K.", meta: "5 past bookings, pays by card" },
    facts: [["Surface", "Patio"], ["Size", "About 25 m²"], ["Re-sanding", "Not needed"],
      ["Water", "Outside tap"], ["When", "Any day"], ["Estimate", "About 70 min"]] },
];

// Dave's own customers, brought onto the platform at the lower fee.
const OWN_CUSTOMERS = [
  { id: "pg", name: "Pat Green", where: "Holmer Green", cat: "mowing", price: 28, freq: "Every 2 weeks", status: "active" },
  { id: "je", name: "John Ellis", where: "Hazlemere", cat: "hedges", price: 55, freq: "Every 3 months", status: "active" },
  { id: "mb", name: "Mary Bishop", where: "Widmer End", cat: "mowing", price: 25, freq: "Every 2 weeks", status: "invited" },
];
// Numbers that already belong to platform customers (the invite-only rule checks against these).
const PLATFORM_PHONES = ["07700900123"];

const UPCOMING = [
  { dow: "Tue", day: 29, time: "9:00", cat: "mowing", where: "Widmer End", price: 32 },
  { dow: "Tue", day: 29, time: "13:30", cat: "mowing", where: "Hazlemere", price: 28 },
  { dow: "Thu", day: 1, time: "13:00", cat: "hedges", where: "Widmer End", price: 55 },
];

const WEEKLY = [96, 148, 172, 210, 188, 236, 204, 212.5];
const WEEK_LABELS = ["3 Aug", "10", "17", "24", "31", "7 Sep", "14", "21"];
const PAYOUTS = [["Fri 18 Sep", 204], ["Fri 11 Sep", 236], ["Fri 4 Sep", 188]];

const UNFILLED = [
  { id: "R-2291", cat: "hedges", where: "Loudwater, HP10", age: "5 hours", guide: 72,
    brief: "About 20 m of hedge, taller than a person, both sides",
    why: "Two providers looked, nobody took it. Guide may be low for ladder work." },
  { id: "R-2288", cat: "clearance", where: "Sands, HP12", age: "9 hours", guide: 110,
    brief: "Car boot's worth of green waste, photos attached",
    why: "Gary suggested £150. Waiting on the customer." },
  { id: "R-2284", cat: "mowing", where: "Princes Risborough, HP27", age: "26 hours", guide: 34,
    brief: "About 200 m² lawn, every 2 weeks, clippings in bin",
    why: "No providers within 4 miles. Nobody has seen it." },
];

const DISTRICTS = [
  { code: "HP15", name: "Hazlemere", jobs: 14, providers: 4 },
  { code: "HP10", name: "Tylers Green, Loudwater", jobs: 9, providers: 2 },
  { code: "HP13", name: "Downley", jobs: 7, providers: 2 },
  { code: "SL7", name: "Marlow", jobs: 6, providers: 1 },
  { code: "HP12", name: "Booker, Sands", jobs: 5, providers: 1 },
  { code: "HP11", name: "Town centre", jobs: 3, providers: 0 },
  { code: "HP9", name: "Beaconsfield", jobs: 2, providers: 0 },
  { code: "HP27", name: "Princes Risborough", jobs: 1, providers: 0 },
];

const DISPUTES = [
  { id: "D-014", title: "Clippings left on the patio", cat: "mowing", where: "Marlow", customer: "Helen M.",
    provider: "Alan P.", opened: "2 days ago", stage: 1, status: "Waiting for Alan's reply", amount: 34 },
  { id: "D-013", title: "Hedge cut lower than agreed", cat: "hedges", where: "Penn", customer: "Richard B.",
    provider: "Sue P.", opened: "5 days ago", stage: 2, status: "Fix proposed: Sue reshapes it free", amount: 68 },
  { id: "D-011", title: "Provider didn't arrive", cat: "mowing", where: "Downley", customer: "Priya S.",
    provider: "Jan K.", opened: "12 days ago", stage: 3, status: "Closed: covered by Dave next morning", amount: 30 },
];

// Calibration: estimated vs recorded minutes (seeded so it renders the same every time)
function mulberry32(seed) {
  return function () {
    seed |= 0; seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const CAL_SEGMENTS = [
  { id: "mowing", label: "Mowing, routine", color: "var(--c1)" },
  { id: "first", label: "Mowing, first cut", color: "var(--c2)" },
  { id: "hedges", label: "Hedges", color: "var(--c3)" },
  { id: "clearance", label: "Clearance", color: "var(--c4)" },
];
const CAL_POINTS = (() => {
  const r = mulberry32(11);
  const pts = [];
  const add = (seg, n, lo, hi, fLo, fHi) => {
    for (let i = 0; i < n; i++) {
      const est = lo + r() * (hi - lo);
      pts.push({ seg, est: Math.round(est), act: Math.round(est * (fLo + r() * (fHi - fLo))) });
    }
  };
  add("mowing", 34, 22, 60, 0.85, 1.18);
  add("first", 12, 45, 90, 1.08, 1.55);
  add("hedges", 16, 40, 160, 0.88, 1.38);
  add("clearance", 10, 90, 220, 0.72, 1.45);
  return pts;
})();
const CAL_TABLE = [
  { seg: "Mowing, routine", jobs: 118, guide: 0.74, counter: 0.26, uplift: 4, overrun: 0.03, over25: 0.06 },
  { seg: "Mowing, first cut", jobs: 14, guide: 0.43, counter: 0.57, uplift: 9, overrun: 0.31, over25: 0.36 },
  { seg: "Hedges", jobs: 29, guide: 0.38, counter: 0.62, uplift: 14, overrun: 0.12, over25: 0.21 },
  { seg: "Clearance", jobs: 17, guide: 0.18, counter: 0.82, uplift: 35, overrun: 0.08, over25: 0.24 },
];

/* ================================ Styles ================================ */
/*
 * Everything visual flows from the token blocks below. Components only ever
 * reference var(--token). Picking a winning version = keep one block.
 */
const CSS = `
@import url('https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,800&family=Figtree:wght@400;500;600;700&family=Instrument+Sans:wght@400;500;600;700&family=Work+Sans:wght@400;500;600;700&family=Young+Serif&display=swap');

/* ---------- prototype shell (not part of the product) ---------- */
.pt-shell{min-height:100vh;background:#15181a}
.shell-bar{position:sticky;top:0;z-index:60;display:flex;flex-wrap:wrap;align-items:center;gap:8px 12px;padding:10px 14px;background:#15181a;color:#e9ebe6;font:500 14px/1.2 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;border-bottom:1px solid #272b2e}
.shell-title{font-weight:700;margin-right:4px}
.shell-title span{font-weight:500;color:#8e948d;margin-left:6px}
.seg{display:inline-flex;background:#23272a;border-radius:10px;padding:3px;gap:2px}
.seg button{border:0;background:transparent;color:#b2b7b0;padding:7px 11px;border-radius:8px;font:600 13px/1 system-ui,-apple-system,sans-serif;cursor:pointer;display:inline-flex;align-items:center;gap:6px}
.seg button:hover{color:#fff}
.seg button.on{background:#e9ebe6;color:#15181a}
.swatch{width:10px;height:10px;border-radius:50%;display:inline-block;box-shadow:inset 0 0 0 1px rgba(255,255,255,.35)}
.shell-select{background:#23272a;color:#e9ebe6;border:0;border-radius:8px;padding:8px 10px;font:500 13px system-ui,sans-serif}
.shell-bar :focus-visible{outline:2px solid #9ecbff;outline-offset:2px}
@media(max-width:640px){.shell-bar{position:relative}.shell-title{width:100%}.shell-select{width:100%}}

/* ---------- shared tokens ---------- */
.pt{--ok:#2C7549;--ok-soft:#DFF0E4;--warn:#8F5B0C;--warn-soft:#FAEED5;--danger:#A2352A;--danger-soft:#F7E0DC;--star:#DE9E1F;--press:0px;
  font-family:var(--font-body);color:var(--ink);background:var(--bg);font-size:16px;line-height:1.5;-webkit-font-smoothing:antialiased;min-height:calc(100vh - 57px);position:relative}

/* ---------- Version 1: Village (warm, neighbourly; seed packet / notice board) ---------- */
.pt[data-theme="village"]{--bg:#F2F4EE;--surface:#FFFFFF;--soft:#E7EBE1;--ink:#18261E;--muted:#56645B;--line:#D3DACB;--hair:#E2E7DB;
  --primary:#1E4B38;--on-primary:#FFFFFF;--primary-soft:#DCE8DF;--accent:#F2B233;--on-accent:#18261E;--accent-soft:#FCEFCF;
  --font-head:"Young Serif",Georgia,serif;--font-body:"Figtree",system-ui,-apple-system,"Segoe UI",sans-serif;--head-weight:400;--head-track:-0.01em;
  --radius:24px;--radius-sm:14px;--btn-radius:999px;--bw:1px;--btn-border:transparent;--btn-shadow:none;
  --shadow:0 1px 2px rgba(24,38,30,.05),0 14px 32px -18px rgba(24,38,30,.28);
  --lawn-1:#5E995A;--lawn-2:#74AE6B;--hedge:#2E5D3E;--house:#FFFFFF;--roof:#1E4B38;--path:#D6DDCC;--sky:#E2E9D8;
  --c1:#1E4B38;--c2:#E3A21F;--c3:#5F93BC;--c4:#98A39A}

/* ---------- Version 2: Studio (clean, premium; type does the work) ---------- */
.pt[data-theme="studio"]{--bg:#FAFAF8;--surface:#FFFFFF;--soft:#F1F2EE;--ink:#1A211D;--muted:#5E6661;--line:#E1E4DE;--hair:#ECEEE9;
  --primary:#163A2E;--on-primary:#FFFFFF;--primary-soft:#E4ECE7;--accent:#163A2E;--on-accent:#FFFFFF;--accent-soft:#E9EFE6;
  --font-head:"Instrument Sans",system-ui,-apple-system,sans-serif;--font-body:"Instrument Sans",system-ui,-apple-system,"Segoe UI",sans-serif;--head-weight:600;--head-track:-0.035em;
  --radius:12px;--radius-sm:8px;--btn-radius:8px;--bw:1px;--btn-border:transparent;--btn-shadow:none;
  --shadow:0 1px 2px rgba(26,33,29,.05);
  --lawn-1:#A7BEAC;--lawn-2:#B8CCBC;--hedge:#3D5D4D;--house:#FFFFFF;--roof:#163A2E;--path:#E1E4DE;--sky:#EEF1EC;
  --c1:#163A2E;--c2:#7FA38E;--c3:#C08A3E;--c4:#A7ADA9}

/* ---------- Version 3: Toolshed (bold, earthy; moss and strimmer orange) ---------- */
.pt[data-theme="toolshed"]{--bg:#E9EBDD;--surface:#FFFFFF;--soft:#F3F4EA;--ink:#17200F;--muted:#4B5543;--line:#17200F;--hair:#CDD2BD;
  --primary:#2B4A1E;--on-primary:#FFFFFF;--primary-soft:#DFE9D2;--accent:#FF7417;--on-accent:#17200F;--accent-soft:#FFE3CC;
  --font-head:"Bricolage Grotesque",system-ui,-apple-system,sans-serif;--font-body:"Work Sans",system-ui,-apple-system,"Segoe UI",sans-serif;--head-weight:800;--head-track:-0.025em;
  --radius:16px;--radius-sm:10px;--btn-radius:12px;--bw:2px;--btn-border:#17200F;--btn-shadow:3px 3px 0 #17200F;--press:2px;
  --shadow:5px 5px 0 #17200F;
  --lawn-1:#8DBE45;--lawn-2:#A4CF5C;--hedge:#2B4A1E;--house:#F3F4EA;--roof:#17200F;--path:#D5D8C4;--sky:#F3F4EA;
  --c1:#2B4A1E;--c2:#FF7417;--c3:#5E82CF;--c4:#8A907F}

/* ---------- base ---------- */
.pt *,.pt *::before,.pt *::after{box-sizing:border-box}
.pt [hidden]{display:none!important}
.pt h1,.pt h2,.pt h3{font-family:var(--font-head);font-weight:var(--head-weight);letter-spacing:var(--head-track);line-height:1.12;margin:0}
.pt p{margin:0}
.pt button{font:inherit;color:inherit;cursor:pointer}
.pt input,.pt textarea{font:inherit;color:inherit}
.pt hr{border:0;height:1px;background:var(--hair);margin:2px 0;width:100%}
.pt a{color:var(--primary)}
.pt :focus-visible{outline:3px solid var(--primary);outline-offset:2px}
@media(prefers-reduced-motion:reduce){.pt *{animation:none!important;transition:none!important}}

.display{font-size:clamp(38px,6.4vw,68px);line-height:1.02!important}
.h1{font-size:clamp(27px,4.2vw,36px)}
.h2{font-size:23px}
.h3{font-size:18px}
.lead{font-size:18.5px;line-height:1.5;color:var(--muted);max-width:32em}
.muted{color:var(--muted)}
.small{font-size:14.5px}
.xs{font-size:13px}
.center{text-align:center}
.kicker{font-size:15px;font-weight:600;color:var(--primary)}
.stack{display:flex;flex-direction:column;gap:var(--g,12px)}
.row{display:flex;align-items:center;gap:var(--g,10px)}
.between{justify-content:space-between}
.wrap{flex-wrap:wrap}
.grow{flex:1;min-width:0}
.top{align-items:flex-start}
.grid2{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
.grid3{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}
.split{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}
@media(max-width:820px){.grid3,.split{grid-template-columns:1fr}}

.card{background:var(--surface);border:var(--bw) solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow);padding:20px}
.card.flat{box-shadow:none}
.soft{background:var(--soft);border-radius:var(--radius-sm);padding:14px 16px}

/* ---------- buttons ---------- */
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;min-height:48px;padding:0 20px;border-radius:var(--btn-radius);border:var(--bw) solid var(--btn-border);background:var(--soft);box-shadow:var(--btn-shadow);font-weight:600;font-size:16px;line-height:1.1;text-decoration:none;white-space:nowrap;transition:transform .08s ease,box-shadow .08s ease,filter .15s ease}
.btn:hover{filter:brightness(.97)}
.btn-primary:hover,.btn-cta:hover{filter:brightness(1.08)}
.btn:active{transform:translate(var(--press),var(--press));box-shadow:none}
.btn[disabled]{opacity:.45;cursor:not-allowed;transform:none;filter:none}
.btn-primary{background:var(--primary);color:var(--on-primary)}
.btn-cta{background:var(--accent);color:var(--on-accent)}
.btn-ghost{background:var(--surface);border-color:var(--line);box-shadow:none}
.btn-link{background:none;border:0;box-shadow:none;min-height:0;padding:0;color:var(--primary);font-weight:600}
.btn-link:active{transform:none}
.btn-lg{min-height:58px;font-size:17px;padding:0 26px}
.btn-sm{min-height:36px;font-size:14px;padding:0 12px;gap:6px}
.btn-block{width:100%}
.icon-btn{width:44px;height:44px;display:grid;place-items:center;border-radius:999px;border:var(--bw) solid var(--line);background:var(--surface);flex:none}

/* ---------- form controls ---------- */
.chip{display:inline-flex;align-items:center;gap:6px;min-height:44px;padding:0 16px;border-radius:999px;border:var(--bw) solid var(--line);background:var(--surface);font-weight:500;font-size:15px;white-space:nowrap}
.chip.on{background:var(--primary);border-color:var(--primary);color:var(--on-primary)}
.chip.quiet{color:var(--muted);cursor:default;background:transparent;min-height:36px;font-size:14px}
.chips{display:flex;flex-wrap:wrap;gap:8px}
.choice{display:flex;align-items:flex-start;gap:12px;width:100%;text-align:left;padding:14px 16px;border-radius:var(--radius-sm);border:var(--bw) solid var(--line);background:var(--surface)}
.choice.on{border-color:var(--primary);background:var(--primary-soft);box-shadow:inset 0 0 0 1px var(--primary)}
.tick{width:22px;height:22px;border-radius:999px;border:2px solid var(--muted);display:grid;place-items:center;flex:none;margin-top:1px}
.choice.on .tick{background:var(--primary);border-color:var(--primary);color:var(--on-primary)}
.field{display:flex;flex-direction:column;gap:8px}
.label{font-weight:600;font-size:15.5px}
.hint{font-size:14px;color:var(--muted)}
.input{width:100%;height:52px;padding:0 14px;border-radius:var(--radius-sm);border:var(--bw) solid var(--line);background:var(--surface);font-size:16px}
.input:focus{outline:none;border-color:var(--primary);box-shadow:0 0 0 3px var(--primary-soft)}
textarea.input{height:auto;min-height:96px;padding:12px 14px;resize:vertical;line-height:1.45}
.input-icon{position:relative}
.input-icon>svg{position:absolute;left:14px;top:50%;transform:translateY(-50%);color:var(--muted);pointer-events:none}
.input-icon .input{padding-left:42px}
.checkbox-row{display:flex;gap:12px;align-items:flex-start;background:none;border:0;text-align:left;padding:0}
.box{width:24px;height:24px;border-radius:7px;border:2px solid var(--muted);display:grid;place-items:center;flex:none;margin-top:1px;background:var(--surface)}
.box.on{background:var(--primary);border-color:var(--primary);color:var(--on-primary)}
.stepper{display:inline-flex;align-items:center;border:var(--bw) solid var(--line);border-radius:var(--radius-sm);background:var(--surface);overflow:hidden}
.stepper button{width:52px;height:52px;border:0;background:var(--soft);display:grid;place-items:center}
.stepper button[disabled]{opacity:.35;cursor:not-allowed}
.stepper-val{min-width:108px;text-align:center;font-family:var(--font-head);font-weight:var(--head-weight);font-size:22px;padding:0 8px;font-variant-numeric:tabular-nums}
.toggle-row{display:flex;align-items:center;gap:14px;width:100%;padding:12px 0;background:none;border:0;text-align:left}
.switch{width:50px;height:30px;border-radius:99px;background:var(--hair);position:relative;flex:none;transition:background .2s}
.switch i{position:absolute;top:3px;left:3px;width:24px;height:24px;border-radius:50%;background:#fff;box-shadow:0 1px 3px rgba(0,0,0,.25);transition:transform .2s}
.switch.on{background:var(--primary)}
.switch.on i{transform:translateX(20px)}
.tabs{display:flex;gap:4px;background:var(--soft);padding:4px;border-radius:calc(var(--radius-sm) + 4px)}
.tabs button{flex:1;border:0;background:transparent;padding:10px 8px;border-radius:var(--radius-sm);font-weight:600;font-size:15px;color:var(--muted)}
.tabs button.on{background:var(--surface);color:var(--ink);box-shadow:0 1px 3px rgba(0,0,0,.08)}
.pt[data-theme="toolshed"] .tabs button.on{box-shadow:inset 0 0 0 2px var(--ink)}

/* ---------- small pieces ---------- */
.badge{display:inline-flex;align-items:center;gap:5px;padding:3px 9px;border-radius:999px;font-size:12.5px;font-weight:600;background:var(--soft);color:var(--ink);white-space:nowrap;line-height:1.45}
.badge.ok{background:var(--ok-soft);color:var(--ok)}
.badge.warn{background:var(--warn-soft);color:var(--warn)}
.badge.danger{background:var(--danger-soft);color:var(--danger)}
.badge.accent{background:var(--accent-soft);color:var(--ink)}
.avatar{border-radius:999px;display:grid;place-items:center;background:var(--accent-soft);color:var(--primary);font-family:var(--font-head);font-weight:var(--head-weight);flex:none}
.pt[data-theme="toolshed"] .avatar{border:2px solid var(--ink)}
.stars{display:inline-flex;gap:1px}
.star{display:inline-flex;color:var(--muted);opacity:.35}
.star.on{color:var(--star);opacity:1}
.star-btn{background:none;border:0;padding:4px;color:var(--muted);opacity:.4}
.star-btn.on{color:var(--star);opacity:1}
.progress{height:6px;background:var(--hair);border-radius:99px;overflow:hidden}
.progress>i{display:block;height:100%;background:var(--primary);border-radius:99px;transition:width .35s ease}
.toast{position:fixed;left:50%;bottom:24px;transform:translateX(-50%);background:var(--ink);color:var(--bg);padding:12px 18px;border-radius:12px;font-size:14.5px;font-weight:500;z-index:100;box-shadow:0 10px 30px rgba(0,0,0,.25);width:max-content;max-width:min(92vw,460px);text-align:center;animation:pt-up .25s ease}
@keyframes pt-up{from{opacity:0;transform:translate(-50%,8px)}to{opacity:1;transform:translate(-50%,0)}}
.success-mark{width:64px;height:64px;border-radius:50%;background:var(--primary);color:var(--on-primary);display:grid;place-items:center;flex:none}
.success-mark.sm{width:44px;height:44px}
.dot{width:10px;height:10px;border-radius:50%;display:inline-block;flex:none}
.dot-provider{background:var(--primary)}
.dot-fee{background:var(--accent)}
.pt[data-theme="studio"] .dot-fee{background:var(--c2)}
.cat-ico{width:40px;height:40px;border-radius:12px;background:var(--primary-soft);color:var(--primary);display:grid;place-items:center;flex:none}
.cat-ico.lg{width:54px;height:54px;border-radius:15px}
.cat-ico.sm{width:34px;height:34px;border-radius:10px}
.big-num{font-family:var(--font-head);font-weight:var(--head-weight);letter-spacing:var(--head-track);font-size:36px;line-height:1;font-variant-numeric:tabular-nums}
.kv{display:grid;grid-template-columns:auto 1fr;gap:10px 18px;font-size:15.5px;margin:0}
.kv dt{color:var(--muted)}
.kv dd{margin:0;font-weight:500}
.list-row{display:flex;align-items:center;gap:12px;padding:14px 0;border-bottom:1px solid var(--hair)}
.list-row:last-child{border-bottom:0}
.date-chip{width:52px;flex:none;text-align:center;border-radius:12px;background:var(--soft);padding:6px 0;line-height:1.1}
.date-chip b{display:block;font-family:var(--font-head);font-weight:var(--head-weight);font-size:20px}
.date-chip span{font-size:12px;color:var(--muted);font-weight:600}

/* ---------- customer ---------- */
.c-header{display:flex;align-items:center;justify-content:space-between;gap:12px;max-width:1140px;margin:0 auto;padding:16px 20px}
.brand{display:inline-flex;align-items:center;gap:9px;font-family:var(--font-head);font-weight:var(--head-weight);font-size:23px;letter-spacing:var(--head-track);background:none;border:0;padding:0;color:var(--ink)}
.brand-mark{width:32px;height:32px;border-radius:10px;background:var(--primary);color:var(--on-primary);display:grid;place-items:center;flex:none}
.pt[data-theme="village"] .brand-mark{border-radius:50% 50% 50% 10px}
.pt[data-theme="toolshed"] .brand-mark{background:var(--accent);color:var(--ink);border:2px solid var(--ink)}
.brand.sm{font-size:19px}
.brand.sm .brand-mark{width:26px;height:26px}
.c-wrap{max-width:1140px;margin:0 auto;padding:0 20px 56px}
.c-flow{max-width:600px;margin:0 auto;padding:4px 20px 64px;display:flex;flex-direction:column;gap:22px}
.c-flow.wide{max-width:760px}
.flow-top{display:flex;align-items:center;gap:14px}
.c-section{padding-top:56px}
.c-section-title{margin-bottom:20px}
.c-footer{max-width:1140px;margin:0 auto;padding:28px 20px 44px;border-top:1px solid var(--hair);display:flex;flex-direction:column;gap:8px}
@media(max-width:640px){.hide-sm{display:none!important}.c-header{padding:12px 16px}.c-wrap{padding:0 16px 48px}.c-flow{padding:4px 16px 56px}.c-section{padding-top:40px}}

.quote-card{padding:22px}
.cat-tiles{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}
.cat-tile{display:flex;flex-direction:column;align-items:flex-start;gap:6px;padding:14px 12px;border-radius:var(--radius-sm);border:var(--bw) solid var(--line);background:var(--surface);text-align:left;min-height:112px}
.cat-tile.on{border-color:var(--primary);background:var(--primary-soft);box-shadow:inset 0 0 0 1px var(--primary)}
.cat-tile.on .cat-ico{background:var(--primary);color:var(--on-primary)}
.cat-name{font-weight:600;font-size:15px;line-height:1.2}
@media(max-width:420px){.cat-tile{padding:12px 10px;min-height:104px}.cat-name{font-size:14px}}

/* Village hero: copy + quote left, illustrated garden right */
.hero-v{display:grid;grid-template-columns:minmax(0,1.05fr) minmax(0,.95fr);gap:48px;align-items:center;padding:28px 0 8px}
.hero-art{position:relative}
.garden-art{width:100%;height:auto;display:block}
.float-card{position:absolute;display:flex;align-items:center;gap:10px;background:var(--surface);border:var(--bw) solid var(--line);border-radius:var(--radius-sm);padding:10px 14px;box-shadow:var(--shadow)}
.fc-1{left:-18px;bottom:34px}
.fc-2{right:18px;top:18px;flex-direction:column;align-items:flex-start;gap:0}
@media(max-width:900px){.hero-v{grid-template-columns:1fr;gap:28px}.fc-1{left:10px}}

/* Studio hero: centred, type-led */
.hero-s{display:flex;flex-direction:column;align-items:center;text-align:center;gap:22px;padding:56px 0 8px}
.hero-s .display{max-width:12em;font-size:clamp(40px,7.4vw,84px);letter-spacing:-.045em}
.hero-s .lead{margin:0 auto}
.hero-s .quote-card{width:100%;max-width:640px;text-align:left}
.proof{display:flex;flex-wrap:wrap;justify-content:center;gap:10px 28px;color:var(--muted);font-size:14.5px}
.proof span{display:inline-flex;align-items:center;gap:7px}

/* Toolshed hero: moss block + sticker */
.hero-t{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,.9fr);gap:24px;align-items:stretch;padding:20px 0 8px}
.t-panel{position:relative;background:var(--primary);color:var(--on-primary);border:2px solid var(--ink);border-radius:var(--radius);box-shadow:var(--shadow);padding:40px 32px;display:flex;flex-direction:column;justify-content:flex-end;gap:18px;min-height:440px;overflow:hidden}
.t-panel .lead{color:var(--on-primary);opacity:.88}
.t-panel .kicker{color:var(--accent)}
.t-stripes{position:absolute;inset:0 0 auto 0;height:46%;background:repeating-linear-gradient(90deg,rgba(255,255,255,.07) 0 38px,transparent 38px 76px)}
.sticker{position:absolute;top:26px;right:26px;width:118px;height:118px;border-radius:50%;background:var(--accent);color:var(--on-accent);border:2px solid var(--ink);display:grid;place-items:center;text-align:center;font-family:var(--font-head);font-weight:800;font-size:17px;line-height:1.05;padding:14px;transform:rotate(-10deg)}
@media(max-width:900px){.hero-t{grid-template-columns:1fr}.t-panel{min-height:360px;padding:28px 22px}.sticker{width:96px;height:96px;font-size:14px;top:16px;right:16px}}

.step-ico{width:42px;height:42px;border-radius:12px;display:grid;place-items:center;background:var(--accent-soft);color:var(--ink)}
.step-n{font-family:var(--font-head);font-weight:var(--head-weight);color:var(--muted);font-size:15px}
.check-row{display:flex;gap:12px;align-items:flex-start}
.check-row .ci{width:36px;height:36px;border-radius:10px;background:var(--primary-soft);color:var(--primary);display:grid;place-items:center;flex:none}
.fee-bar{height:14px;border-radius:99px;background:var(--accent);overflow:hidden;display:flex}
.fee-bar>i{display:block;height:100%;background:var(--primary)}
.pt[data-theme="studio"] .fee-bar{background:var(--c2)}
.pt[data-theme="toolshed"] .fee-bar{border:2px solid var(--ink);height:18px}

.plot{width:100%;height:auto;display:block;max-height:420px}
.plot-label{font-size:11.5px;font-weight:600;fill:var(--ink);font-family:var(--font-body)}
.plot-lawn{cursor:pointer}
.plot-lawn:focus{outline:none}
.plot-lawn:focus-visible rect{stroke-width:4px}
.price-big{font-family:var(--font-head);font-weight:var(--head-weight);letter-spacing:var(--head-track);font-size:clamp(56px,12vw,76px);line-height:.95;font-variant-numeric:tabular-nums}
.conf{display:flex;gap:4px}
.conf i{height:6px;width:28px;border-radius:99px;background:var(--hair)}
.conf i.on{background:var(--primary)}
.num-item{display:flex;gap:12px;align-items:flex-start}
.num-item .n{width:26px;height:26px;border-radius:50%;background:var(--primary-soft);color:var(--primary);display:grid;place-items:center;font-size:13px;font-weight:700;flex:none}
.photo-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}
.photo{aspect-ratio:1;border-radius:var(--radius-sm);position:relative;overflow:hidden;background:linear-gradient(155deg,var(--lawn-2),var(--hedge))}
.photo::after{content:"";position:absolute;inset:0;background:radial-gradient(circle at 30% 70%,rgba(255,255,255,.2),transparent 45%),repeating-linear-gradient(100deg,rgba(0,0,0,.09) 0 3px,transparent 3px 11px)}
.photo .x{position:absolute;top:6px;right:6px;z-index:2;width:28px;height:28px;border-radius:50%;border:0;background:rgba(0,0,0,.55);color:#fff;display:grid;place-items:center}
.photo-add{aspect-ratio:1;border-radius:var(--radius-sm);border:var(--bw) dashed var(--muted);background:var(--surface);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:4px;color:var(--muted);font-size:13px;font-weight:600}
.card-mock{display:flex;align-items:center;gap:10px;height:52px;padding:0 14px;border-radius:var(--radius-sm);border:var(--bw) solid var(--line);background:var(--surface);font-variant-numeric:tabular-nums}

.pulse{width:12px;height:12px;border-radius:50%;background:var(--primary);position:relative;flex:none}
.pulse::after{content:"";position:absolute;inset:-6px;border-radius:50%;border:2px solid var(--primary);animation:pt-pulse 1.6s ease-out infinite}
@keyframes pt-pulse{from{transform:scale(.5);opacity:1}to{transform:scale(1.6);opacity:0}}
.tl-item{display:flex;gap:14px;padding-bottom:18px;position:relative;animation:pt-in .35s ease}
.tl-item::before{content:"";position:absolute;left:15px;top:34px;bottom:2px;width:2px;background:var(--hair)}
.tl-item:last-child::before{display:none}
.tl-ico{width:32px;height:32px;border-radius:50%;display:grid;place-items:center;background:var(--soft);color:var(--muted);flex:none}
.tl-ico.good{background:var(--primary);color:var(--on-primary)}
.tl-ico.alert{background:var(--accent-soft);color:var(--ink)}
@keyframes pt-in{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}

.bubble-row{display:flex}
.bubble-row.me{justify-content:flex-end}
.msg{max-width:80%;padding:10px 14px;border-radius:18px;background:var(--soft);font-size:15px}
.bubble-row.me .msg{background:var(--primary);color:var(--on-primary)}
.thumb{width:56px;height:56px;border-radius:12px;flex:none;background:repeating-linear-gradient(90deg,var(--lawn-1) 0 10px,var(--lawn-2) 10px 20px)}

/* ---------- provider ---------- */
.p-stage{display:flex;justify-content:center;padding:28px 12px 40px}
.p-phone{width:100%;max-width:410px;height:820px;background:var(--bg);border-radius:38px;box-shadow:0 0 0 9px #202421,0 30px 70px rgba(0,0,0,.35);overflow:hidden;display:flex;flex-direction:column;position:relative}
.p-top{display:flex;align-items:center;justify-content:space-between;padding:14px 18px;background:var(--surface);border-bottom:1px solid var(--hair);flex:none}
.p-body{flex:1;overflow-y:auto;padding:18px 16px 28px;font-size:17px;display:flex;flex-direction:column;gap:18px}
.p-body .small{font-size:15.5px}
.p-body .xs{font-size:14px}
.p-body .label{font-size:16.5px}
.p-nav{display:grid;grid-template-columns:repeat(4,1fr);background:var(--surface);border-top:1px solid var(--hair);padding:4px 4px 8px;flex:none}
.p-nav button{background:none;border:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;min-height:60px;font-size:13.5px;font-weight:600;color:var(--muted)}
.p-nav button.on{color:var(--primary)}
@media(max-width:520px){.p-stage{padding:0}.p-phone{max-width:none;height:auto;min-height:calc(100vh - 170px);border-radius:0;box-shadow:none;overflow:visible}.p-body{overflow:visible}.p-nav{position:sticky;bottom:0;z-index:5}}
.offer-card{display:flex;flex-direction:column;gap:12px;text-align:left;width:100%;padding:16px;background:var(--surface);border:var(--bw) solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow);cursor:pointer}
.route-tag{display:inline-flex;align-items:center;gap:6px;background:var(--accent-soft);color:var(--ink);font-size:14px;font-weight:600;padding:6px 11px;border-radius:999px;align-self:flex-start}
.facts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1px;background:var(--hair);border-radius:var(--radius-sm);overflow:hidden;border:1px solid var(--hair);margin:0}
.facts>div{background:var(--surface);padding:12px 14px}
.facts dt{font-size:13.5px;color:var(--muted)}
.facts dd{margin:2px 0 0;font-weight:600;font-size:16px}
.timer{font-family:var(--font-head);font-weight:var(--head-weight);font-size:64px;letter-spacing:-.02em;line-height:1;font-variant-numeric:tabular-nums;text-align:center}
.round-item{display:flex;gap:12px;position:relative;padding-bottom:16px}
.round-item::before{content:"";position:absolute;left:22px;top:48px;bottom:4px;width:2px;background:var(--hair)}
.round-item:last-child::before{display:none}
.round-time{width:46px;height:46px;border-radius:12px;display:grid;place-items:center;background:var(--soft);font-weight:700;font-size:13.5px;flex:none}
.round-item.done .round-time{background:var(--primary-soft);color:var(--primary)}
.round-item.now .round-time{background:var(--primary);color:var(--on-primary)}
.doc-row{display:flex;align-items:center;gap:12px;padding:13px 0;border-bottom:1px solid var(--hair)}
.doc-row:last-child{border-bottom:0}
.sms{display:flex;flex-direction:column;height:100%;background:#fff;color:#111;font-family:-apple-system,system-ui,"Segoe UI",sans-serif}
.sms-head{display:flex;flex-direction:column;align-items:center;gap:4px;padding:18px 16px 12px;background:#f6f6f6;border-bottom:1px solid #e5e5e5}
.sms-av{width:48px;height:48px;border-radius:50%;background:linear-gradient(#a6acb1,#878d93);color:#fff;display:grid;place-items:center;font-weight:600;font-size:20px}
.sms-body{flex:1;overflow-y:auto;padding:16px 14px;display:flex;flex-direction:column;gap:8px}
.sms-day{text-align:center;font-size:12px;color:#8a8a8e;margin:8px 0 2px}
.sms-bubble{align-self:flex-start;max-width:84%;background:#e9e9eb;color:#111;padding:10px 14px;border-radius:20px;font-size:16px;line-height:1.38}
.sms-bubble a{color:#0a64d8;text-decoration:underline;cursor:pointer}
.sms-foot{padding:16px;background:var(--bg);border-top:1px solid var(--hair);font-family:var(--font-body);color:var(--ink)}
@media(max-width:520px){.sms{min-height:calc(100vh - 170px)}}

/* ---------- admin ---------- */
.a-shell{display:grid;grid-template-columns:236px minmax(0,1fr);min-height:calc(100vh - 57px)}
.a-side{background:var(--surface);border-right:1px solid var(--hair);padding:18px 12px;display:flex;flex-direction:column;gap:2px}
.a-brand{padding:4px 10px 18px}
.a-nav{display:flex;align-items:center;gap:10px;padding:10px 12px;border:0;border-radius:var(--radius-sm);background:none;color:var(--muted);font-weight:500;font-size:15px;text-align:left;white-space:nowrap}
.a-nav:hover{background:var(--soft);color:var(--ink)}
.a-nav.on{background:var(--primary-soft);color:var(--primary);font-weight:600}
.a-side-foot{margin-top:auto;padding:12px 10px 0;font-size:13px;color:var(--muted)}
.a-main{padding:26px 30px 56px;display:flex;flex-direction:column;gap:22px;min-width:0}
.a-cols{display:grid;grid-template-columns:minmax(0,1.25fr) minmax(0,1fr);gap:18px;align-items:start}
@media(max-width:1100px){.a-cols{grid-template-columns:1fr}}
@media(max-width:860px){.a-shell{grid-template-columns:1fr}.a-side{flex-direction:row;overflow-x:auto;border-right:0;border-bottom:1px solid var(--hair);padding:8px}.a-brand,.a-side-foot{display:none}.a-main{padding:18px 14px 44px}}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.kpi{padding:16px 18px}
.kpi .v{font-family:var(--font-head);font-weight:var(--head-weight);letter-spacing:var(--head-track);font-size:30px;line-height:1.1;margin-top:4px;font-variant-numeric:tabular-nums}
.table-wrap{overflow-x:auto}
.table{width:100%;border-collapse:collapse;font-size:14.5px}
.table th{text-align:left;font-size:13px;font-weight:600;color:var(--muted);padding:10px 12px;border-bottom:1px solid var(--hair);white-space:nowrap}
.table td{padding:13px 12px;border-bottom:1px solid var(--hair);white-space:nowrap;vertical-align:middle;font-variant-numeric:tabular-nums}
.table tr:last-child td{border-bottom:0}
.table th:first-child,.table td:first-child{padding-left:0}
.req{display:flex;flex-direction:column;gap:10px;padding:16px 0;border-bottom:1px solid var(--hair)}
.req:last-child{border-bottom:0;padding-bottom:0}
.req:first-child{padding-top:4px}
.tiles{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
.tile{position:relative;border-radius:var(--radius-sm);overflow:hidden;padding:12px;min-height:86px;border:1px solid var(--hair);background:var(--surface)}
.tile .fill{position:absolute;inset:0;background:var(--primary)}
.tile .in{position:relative;display:flex;flex-direction:column;gap:2px}
.tile.dark{color:var(--on-primary);border-color:transparent}
.tile.dark .muted{color:var(--on-primary);opacity:.8}
.chart{width:100%;height:auto;display:block}
.chart-lbl{font-size:10.5px;fill:var(--muted);font-family:var(--font-body)}
.chart-val{font-size:11.5px;font-weight:700;fill:var(--ink);font-family:var(--font-body)}
.legend{display:flex;flex-wrap:wrap;gap:8px 18px;font-size:13.5px;color:var(--muted)}
.legend span{display:inline-flex;align-items:center;gap:6px}
.insight{border-left:5px solid var(--accent)}
.pt[data-theme="studio"] .insight{border-left-color:var(--c3)}
.stage{display:flex;gap:4px}
.stage i{flex:1;height:6px;border-radius:99px;background:var(--hair)}
.stage i.on{background:var(--primary)}
.code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12.5px;background:var(--soft);border-radius:var(--radius-sm);padding:14px;overflow:auto;max-height:340px;margin:0;line-height:1.5;white-space:pre}
.ident{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:13px;background:var(--soft);padding:2px 6px;border-radius:6px}

/* ---------- expanded catalogue and provider tools ---------- */
.stepper.sm button{width:42px;height:42px}
.stepper.sm .stepper-val{min-width:38px;font-size:18px;padding:0 4px}
.excluded{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px 24px}
@media(max-width:700px){.excluded{grid-template-columns:1fr}}
.ex-row{display:flex;gap:10px;align-items:flex-start}
.ex-ico{width:28px;height:28px;border-radius:50%;display:grid;place-items:center;background:var(--danger-soft);color:var(--danger);flex:none}
.link-row{display:flex;align-items:center;gap:12px;width:100%;padding:14px 0;background:none;border:0;border-bottom:1px solid var(--hair);text-align:left;color:var(--ink)}
.link-row:last-child{border-bottom:0}
.limit-strip{width:100%;text-align:left;padding:14px 16px;cursor:pointer;color:var(--ink)}
.cmp{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:12px 14px;border-radius:var(--radius-sm);border:var(--bw) solid var(--hair)}
.cmp.win{border-color:var(--primary);background:var(--primary-soft);box-shadow:inset 0 0 0 1px var(--primary)}
.req-docs{display:flex;flex-wrap:wrap;gap:6px}
`;

/* ============================ Shared components ============================ */

const ToastCtx = createContext(() => {});
const useToast = () => useContext(ToastCtx);

function CatIcon({ id, size = 20 }) {
  const I = CAT_ICONS[id] || Sprout;
  return <I size={size} strokeWidth={2} aria-hidden="true" />;
}

function Avatar({ initials, size = 44 }) {
  return <div className="avatar" style={{ width: size, height: size, fontSize: size * 0.38 }} aria-hidden="true">{initials}</div>;
}

function Stars({ value = 0, onChange, size = 16 }) {
  return (
    <span className="stars" role={onChange ? "radiogroup" : "img"} aria-label={onChange ? "Rating" : `${value} out of 5`}>
      {[1, 2, 3, 4, 5].map((n) => {
        const on = n <= Math.round(value);
        const icon = <Star size={size} fill={on ? "currentColor" : "none"} strokeWidth={1.8} />;
        return onChange ? (
          <button key={n} type="button" role="radio" aria-checked={n === value} aria-label={`${n} star${n > 1 ? "s" : ""}`}
            className={"star-btn" + (on ? " on" : "")} onClick={() => onChange(n)}>{icon}</button>
        ) : (
          <span key={n} className={"star" + (on ? " on" : "")}>{icon}</span>
        );
      })}
    </span>
  );
}

function Stepper({ value, onChange, min = 0, max = 999, step = 1, format = (v) => v, label, compact }) {
  return (
    <div className={"stepper" + (compact ? " sm" : "")} role="group" aria-label={label}>
      <button type="button" aria-label="Less" disabled={value <= min} onClick={() => onChange(Math.max(min, value - step))}><Minus size={compact ? 17 : 20} /></button>
      <div className="stepper-val" aria-live="polite">{format(value)}</div>
      <button type="button" aria-label="More" disabled={value >= max} onClick={() => onChange(Math.min(max, value + step))}><Plus size={compact ? 17 : 20} /></button>
    </div>
  );
}

function Choice({ on, onClick, label, hint }) {
  return (
    <button type="button" className={"choice" + (on ? " on" : "")} onClick={onClick} aria-pressed={on}>
      <span className="tick">{on && <Check size={14} strokeWidth={3} />}</span>
      <span className="stack" style={{ "--g": "2px" }}>
        <span style={{ fontWeight: 600 }}>{label}</span>
        {hint && <span className="small muted">{hint}</span>}
      </span>
    </button>
  );
}

function Chip({ on, onClick, children }) {
  return <button type="button" className={"chip" + (on ? " on" : "")} onClick={onClick} aria-pressed={!!on}>{children}</button>;
}

function Toggle({ on, onChange, label, hint }) {
  return (
    <button type="button" role="switch" aria-checked={on} className="toggle-row" onClick={() => onChange(!on)}>
      <span className="stack grow" style={{ "--g": "2px" }}>
        <span style={{ fontWeight: 600 }}>{label}</span>
        {hint && <span className="small muted">{hint}</span>}
      </span>
      <span className={"switch" + (on ? " on" : "")}><i /></span>
    </button>
  );
}

function CheckRow({ on, onChange, children }) {
  return (
    <button type="button" role="checkbox" aria-checked={on} className="checkbox-row" onClick={() => onChange(!on)}>
      <span className={"box" + (on ? " on" : "")}>{on && <Check size={15} strokeWidth={3} />}</span>
      <span className="small">{children}</span>
    </button>
  );
}

function BarChart({ data, labels, format = fmt, label }) {
  const W = 340, H = 140;
  const max = Math.max(...data) * 1.18;
  const bw = (W - 8) / data.length;
  return (
    <svg viewBox={`0 0 ${W} ${H + 22}`} className="chart" role="img" aria-label={label}>
      {data.map((v, i) => {
        const h = (v / max) * H;
        const x = 4 + i * bw + bw * 0.17;
        const w = bw * 0.66;
        const last = i === data.length - 1;
        return (
          <g key={i}>
            <rect x={x} y={H - h} width={w} height={h} rx="5" style={{ fill: last ? "var(--accent)" : "var(--primary)", opacity: last ? 1 : 0.55 }} />
            {last && <text x={x + w / 2} y={H - h - 7} textAnchor="middle" className="chart-val">{format(v)}</text>}
            <text x={x + w / 2} y={H + 16} textAnchor="middle" className="chart-lbl">{labels[i]}</text>
          </g>
        );
      })}
    </svg>
  );
}

/* ============================ Customer surface ============================ */

function CustomerApp({ screen, go, theme, quote, setQuote, switchTo }) {
  const cat = catById(quote.categoryId);
  const answers = quote.answers[cat.id];
  const area = lawnArea(quote);
  const est = estimateFor(cat, answers, area);
  const steps = cat.measure ? ["measure", "details", "price", "contact"] : ["details", "price", "contact"];
  const setAnswer = (key, value) =>
    setQuote((q) => ({ ...q, answers: { ...q.answers, [cat.id]: { ...q.answers[cat.id], [key]: value } } }));
  const start = () => go(cat.measure ? "measure" : "details");
  const common = { cat, quote, setQuote, go, steps, est, area };

  return (
    <div>
      <CustomerHeader go={go} switchTo={switchTo} />
      {screen === "landing" && <Landing theme={theme} quote={quote} setQuote={setQuote} onStart={start} />}
      {screen === "measure" && <MeasureScreen {...common} />}
      {screen === "details" && <DetailsScreen {...common} answers={answers} setAnswer={setAnswer} />}
      {screen === "price" && <PriceScreen {...common} />}
      {screen === "contact" && <ContactScreen {...common} />}
      {screen === "offers" && <OffersScreen {...common} />}
      {screen === "booked" && <BookedScreen {...common} />}
      {screen === "account" && <AccountScreen {...common} />}
      {screen === "rate" && <RateScreen {...common} />}
      {screen === "invite" && <InviteScreen go={go} />}
    </div>
  );
}

function CustomerHeader({ go, switchTo }) {
  return (
    <header className="c-header">
      <button type="button" className="brand" onClick={() => go("landing")} aria-label={`${BRAND} home`}>
        <span className="brand-mark"><Sprout size={18} strokeWidth={2.2} /></span>{BRAND}
      </button>
      <div className="row" style={{ "--g": "16px" }}>
        <button type="button" className="btn btn-link hide-sm" onClick={() => switchTo("provider", "onboarding")}>Earn with {BRAND}</button>
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => go("account")}><User size={16} /> My account</button>
      </div>
    </header>
  );
}

function FlowTop({ steps, current, onBack }) {
  const i = Math.max(0, steps.indexOf(current));
  return (
    <div className="flow-top">
      <button type="button" className="icon-btn" onClick={onBack} aria-label="Back"><ArrowLeft size={20} /></button>
      <div className="grow stack" style={{ "--g": "6px" }}>
        <span className="xs muted">Step {i + 1} of {steps.length}</span>
        <div className="progress" aria-hidden="true"><i style={{ width: `${((i + 1) / steps.length) * 100}%` }} /></div>
      </div>
    </div>
  );
}

/* ---------- landing ---------- */

function Landing({ theme, quote, setQuote, onStart }) {
  const Hero = theme === "studio" ? HeroStudio : theme === "toolshed" ? HeroToolshed : HeroVillage;
  return (
    <>
      <div className="c-wrap">
        <Hero quote={quote} setQuote={setQuote} onStart={onStart} />
        <HowItWorks />
        <TrustAndFees />
        <WhatWeDontDo />
      </div>
      <footer className="c-footer">
        <span className="brand sm"><span className="brand-mark"><Sprout size={14} /></span>{BRAND}</span>
        <p className="xs muted">Working in High Wycombe, Marlow, Beaconsfield, Penn, Hazlemere and Princes Risborough.</p>
        <p className="xs muted">Contains public sector information licensed under the Open Government Licence v3.0. Prototype, not a live service.</p>
      </footer>
    </>
  );
}

function QuoteStarter({ quote, setQuote, onStart }) {
  const [group, setGroup] = useState(catById(quote.categoryId).group);
  const cats = CATEGORIES.filter((c) => c.status === "live" && c.group === group);
  const tabName = { outside: "Outside", inside: "Indoors", help: "Help" };
  return (
    <div className="card quote-card stack" style={{ "--g": "18px" }}>
      <div className="stack" style={{ "--g": "12px" }}>
        <span className="label" id="qs-what">What needs doing?</span>
        <div className="tabs" role="tablist" aria-label="Kind of job">
          {GROUPS.map((g) => (
            <button key={g.id} type="button" role="tab" aria-selected={group === g.id} className={group === g.id ? "on" : ""} onClick={() => setGroup(g.id)}>{tabName[g.id]}</button>
          ))}
        </div>
        <div className="cat-tiles" role="group" aria-labelledby="qs-what">
          {cats.map((c) => (
            <button key={c.id} type="button" aria-pressed={quote.categoryId === c.id}
              className={"cat-tile" + (quote.categoryId === c.id ? " on" : "")}
              onClick={() => setQuote((q) => ({ ...q, categoryId: c.id }))}>
              <span className="cat-ico"><CatIcon id={c.id} size={21} /></span>
              <span className="cat-name">{c.name}</span>
              <span className="xs muted">from {fmt(c.fromPrice)}</span>
            </button>
          ))}
        </div>
      </div>
      <label className="field">
        <span className="label">Your address</span>
        <span className="input-icon">
          <MapPin size={18} />
          <input className="input" value={quote.address} placeholder="Start typing your address or postcode"
            onChange={(e) => setQuote((q) => ({ ...q, address: e.target.value }))} />
        </span>
      </label>
      <button type="button" className="btn btn-cta btn-lg btn-block" onClick={onStart} disabled={!quote.address.trim()}>See my price</button>
      <p className="xs muted row" style={{ "--g": "6px" }}><Lock size={13} /> No account needed to see a price. We don't pass your details on.</p>
    </div>
  );
}

function GardenArt() {
  const f = (v) => ({ fill: `var(${v})` });
  return (
    <svg viewBox="0 0 440 380" className="garden-art" aria-hidden="true">
      <defs><clipPath id="pt-lawn-clip"><rect x="30" y="200" width="380" height="150" rx="18" /></clipPath></defs>
      <rect width="440" height="380" rx="28" style={f("--sky")} />
      <rect x="250" y="72" width="150" height="120" rx="6" style={{ ...f("--house"), stroke: "var(--roof)", strokeWidth: 2 }} />
      <path d="M238 80 L325 22 L412 80 Z" style={f("--roof")} />
      <rect x="273" y="108" width="34" height="34" rx="4" style={f("--sky")} />
      <rect x="343" y="108" width="34" height="34" rx="4" style={f("--sky")} />
      <rect x="311" y="150" width="30" height="42" rx="3" style={f("--roof")} />
      <g clipPath="url(#pt-lawn-clip)">
        {Array.from({ length: 10 }).map((_, i) => (
          <rect key={i} x={30 + i * 38} y="200" width="38" height="150" style={f(i % 2 ? "--lawn-1" : "--lawn-2")} />
        ))}
      </g>
      {[42, 80, 118, 156, 194].map((cx, i) => <circle key={i} cx={cx} cy={182 + (i % 2) * 4} r={30} style={f("--hedge")} />)}
      <path d="M306 192 C 306 250, 256 282, 246 350 L 296 350 C 306 292, 342 252, 346 192 Z" style={f("--path")} />
      <g transform="translate(98 262)">
        <rect width="56" height="26" rx="8" style={f("--accent")} />
        <circle cx="11" cy="28" r="7" style={f("--ink")} />
        <circle cx="45" cy="28" r="7" style={f("--ink")} />
        <path d="M52 4 L80 -30" style={{ stroke: "var(--ink)", strokeWidth: 5, strokeLinecap: "round" }} />
      </g>
    </svg>
  );
}

function HeroVillage(props) {
  return (
    <section className="hero-v">
      <div className="stack" style={{ "--g": "22px" }}>
        <span className="kicker">High Wycombe, Marlow, Beaconsfield and Hazlemere</span>
        <h1 className="display">Home and garden jobs, done by people who live nearby.</h1>
        <p className="lead">Get a guide price in under a minute. Someone local picks the job up, and you only pay once it's done.</p>
        <QuoteStarter {...props} />
      </div>
      <div className="hero-art">
        <GardenArt />
        <div className="float-card fc-1">
          <Avatar initials="DH" size={38} />
          <div className="stack" style={{ "--g": "0px" }}>
            <span className="small" style={{ fontWeight: 600 }}>Dave H. took your job</span>
            <span className="xs muted">Lives 1.2 miles away</span>
          </div>
        </div>
        <div className="float-card fc-2">
          <span className="xs muted">Guide price</span>
          <span className="h3" style={{ fontFamily: "var(--font-head)" }}>£30 a visit</span>
        </div>
      </div>
    </section>
  );
}

function HeroStudio(props) {
  return (
    <section className="hero-s">
      <span className="kicker">Home and garden help around High Wycombe</span>
      <h1 className="display">A fair price for the jobs list, in under a minute.</h1>
      <p className="lead">Cleaning, gardens, flat-pack, small repairs and more. Checked local people pick it up. You pay after it's done.</p>
      <QuoteStarter {...props} />
      <div className="proof">
        <span><Star size={16} /> 4.9 average rating</span>
        <span><ShieldCheck size={16} /> Insurance checked for every provider</span>
        <span><Clock size={16} /> Most jobs picked up within the hour</span>
      </div>
    </section>
  );
}

function HeroToolshed(props) {
  return (
    <section className="hero-t">
      <div className="t-panel">
        <div className="t-stripes" aria-hidden="true" />
        <div className="sticker" aria-hidden="true">Pay after it's done</div>
        <span className="kicker">Wycombe, Marlow, Beaconsfield</span>
        <h1 className="display">Get the jobs list sorted by someone local.</h1>
        <p className="lead">Instant guide price. Neighbours with the kit and the know-how, inside and out. No call-backs.</p>
      </div>
      <QuoteStarter {...props} />
    </section>
  );
}

function HowItWorks() {
  const steps = [
    [MapPin, "Get a guide price", "Answer a few quick questions. For lawns, we measure your garden from public survey data. No call-backs, no account."],
    [Users, "Someone local picks it up", "Providers near you accept the guide price or suggest their own. You approve any change before it's booked."],
    [Camera, "Pay when it's done", "You get before and after photos, then your card is charged. Rate the visit and rebook in a tap."],
  ];
  return (
    <section className="c-section">
      <h2 className="h1 c-section-title">How it works</h2>
      <div className="grid3">
        {steps.map(([I, t, d], i) => (
          <div key={t} className="card stack" style={{ "--g": "10px" }}>
            <div className="row between"><span className="step-ico"><I size={20} /></span><span className="step-n">Step {i + 1}</span></div>
            <h3 className="h3">{t}</h3>
            <p className="muted">{d}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

function TrustAndFees() {
  const { provider, fee } = split(30);
  const checks = [
    [BadgeCheck, "ID checked", "Every provider, before their first job. Anyone working inside your home also has a basic DBS check."],
    [ShieldCheck, "Insurance checked", "Public liability cover verified, and expiry dates tracked. Ladder and pet work need the right cover too."],
    [Star, "Rated after every visit", "Low ratings are followed up. Repeated problems mean removal."],
    [MapPin, "Genuinely local", "Most live within a couple of miles of the jobs they take."],
  ];
  return (
    <section className="c-section split">
      <div className="card stack" style={{ "--g": "16px" }}>
        <h2 className="h2">Who does the work</h2>
        <p className="muted">Retired tradespeople, experienced cleaners, keen gardeners and handy neighbours who want flexible work.</p>
        <div className="stack" style={{ "--g": "14px" }}>
          {checks.map(([I, t, d]) => (
            <div key={t} className="check-row">
              <span className="ci"><I size={18} /></span>
              <div className="stack" style={{ "--g": "1px" }}><b>{t}</b><span className="small muted">{d}</span></div>
            </div>
          ))}
        </div>
      </div>
      <div className="card stack" style={{ "--g": "16px" }}>
        <h2 className="h2">Where your money goes</h2>
        <p className="muted">On a {fmt(30)} job:</p>
        <div className="fee-bar" aria-hidden="true"><i style={{ width: `${(1 - TAKE_RATE) * 100}%` }} /></div>
        <div className="stack" style={{ "--g": "8px" }}>
          <div className="row between"><span className="row" style={{ "--g": "8px" }}><span className="dot dot-provider" /> Your provider</span><b>{fmt(provider)}</b></div>
          <div className="row between"><span className="row" style={{ "--g": "8px" }}><span className="dot dot-fee" /> {BRAND} fee ({pct(TAKE_RATE)})</span><b>{fmt(fee)}</b></div>
        </div>
        <div className="soft small">Your agreement is with the person doing the work. {BRAND} arranges the booking, takes payment on their behalf through Stripe, and helps sort things out if something goes wrong.</div>
      </div>
    </section>
  );
}

function LawnPlot({ lawns, onToggle }) {
  const lawnStyle = (on) => ({
    fill: on ? "url(#pt-stripes)" : "var(--surface)",
    stroke: on ? "var(--primary)" : "var(--muted)",
    strokeWidth: 2, strokeDasharray: on ? "0" : "6 5", transition: "fill .2s",
  });
  const key = (k) => (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onToggle(k); } };
  const label = { stroke: "var(--surface)", strokeWidth: 4, paintOrder: "stroke" };
  return (
    <svg viewBox="0 0 320 380" className="plot" role="group" aria-label="Plan of your garden">
      <defs>
        <pattern id="pt-stripes" width="24" height="24" patternUnits="userSpaceOnUse">
          <rect width="12" height="24" style={{ fill: "var(--lawn-1)" }} />
          <rect x="12" width="12" height="24" style={{ fill: "var(--lawn-2)" }} />
        </pattern>
      </defs>
      <rect width="320" height="34" style={{ fill: "var(--soft)" }} />
      <text x="160" y="22" textAnchor="middle" className="plot-label">Orchard Way</text>
      <rect x="30" y="44" width="260" height="326" rx="4" style={{ fill: "none", stroke: "var(--muted)", strokeWidth: 1.5, strokeDasharray: "6 5" }} />
      <g className="plot-lawn" role="button" tabIndex={0} aria-pressed={lawns.front} aria-label={`Front lawn, ${LAWNS.front} square metres`} onClick={() => onToggle("front")} onKeyDown={key("front")}>
        <rect x="44" y="56" width="150" height="70" rx="6" style={lawnStyle(lawns.front)} />
        <text x="119" y="95" textAnchor="middle" className="plot-label" style={label}>Front, {LAWNS.front} m²</text>
      </g>
      <rect x="206" y="56" width="70" height="122" rx="4" style={{ fill: "var(--path)" }} />
      <text x="241" y="121" textAnchor="middle" className="plot-label">Drive</text>
      <rect x="44" y="138" width="150" height="78" rx="4" style={{ fill: "var(--house)", stroke: "var(--roof)", strokeWidth: 1.5 }} />
      <text x="119" y="181" textAnchor="middle" className="plot-label">House</text>
      <g className="plot-lawn" role="button" tabIndex={0} aria-pressed={lawns.back} aria-label={`Back lawn, ${LAWNS.back} square metres`} onClick={() => onToggle("back")} onKeyDown={key("back")}>
        <rect x="44" y="228" width="232" height="130" rx="6" style={lawnStyle(lawns.back)} />
        <text x="140" y="300" textAnchor="middle" className="plot-label" style={label}>Back, {LAWNS.back} m²</text>
      </g>
      <rect x="44" y="228" width="120" height="22" rx="3" style={{ fill: "var(--path)" }} />
      <text x="104" y="243" textAnchor="middle" className="plot-label">Patio</text>
      <rect x="234" y="316" width="34" height="32" rx="3" style={{ fill: "var(--house)", stroke: "var(--roof)", strokeWidth: 1.5 }} />
      <text x="251" y="336" textAnchor="middle" className="plot-label" style={{ fontSize: 9 }}>Shed</text>
    </svg>
  );
}

function MeasureScreen({ quote, setQuote, go, steps, area }) {
  const toggle = (k) => setQuote((q) => ({ ...q, lawns: { ...q.lawns, [k]: !q.lawns[k] } }));
  const adj = [["smaller", "Looks smaller"], ["right", "About right"], ["bigger", "Looks bigger"]];
  return (
    <div className="c-flow">
      <FlowTop steps={steps} current="measure" onBack={() => go("landing")} />
      <div className="stack" style={{ "--g": "8px" }}>
        <h1 className="h1">Is this your lawn?</h1>
        <p className="muted">We've measured it from public survey data. Tap a lawn to include it or leave it out.</p>
      </div>
      <div className="card flat stack" style={{ "--g": "12px" }}>
        <div className="row small"><MapPin size={16} /><span className="grow">{quote.address}</span><button type="button" className="btn btn-link small" onClick={() => go("landing")}>Change</button></div>
        <LawnPlot lawns={quote.lawns} onToggle={toggle} />
      </div>
      <div className="card stack" style={{ "--g": "14px" }}>
        <div className="row between top">
          <div className="stack" style={{ "--g": "8px" }}><span className="small muted">Lawn to mow</span><span className="big-num">{area} m²</span></div>
          <span className="badge">give or take 15%</span>
        </div>
        <span className="label">Does that look about right?</span>
        <div className="chips">{adj.map(([v, l]) => <Chip key={v} on={quote.areaAdj === v} onClick={() => setQuote((q) => ({ ...q, areaAdj: v }))}>{l}</Chip>)}</div>
        <p className="small muted">It's only used to estimate how long the job takes. Your provider sees the same figure and can suggest a different price if it's off.</p>
      </div>
      <button type="button" className="btn btn-cta btn-lg btn-block" disabled={area === 0} onClick={() => go("details")}>Continue</button>
      {area === 0 && <p className="small center" style={{ color: "var(--danger)" }}>Tap at least one lawn to continue.</p>}
      <p className="xs muted center">Lawn area from Environment Agency LIDAR at 1 m resolution. Contains public sector information licensed under the Open Government Licence v3.0.</p>
    </div>
  );
}

function PhotoPicker({ count, onChange }) {
  return (
    <div className="photo-grid">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="photo" style={{ filter: `hue-rotate(${i * 16}deg)` }} role="img" aria-label={`Photo ${i + 1}`}>
          <button type="button" className="x" aria-label={`Remove photo ${i + 1}`} onClick={() => onChange(count - 1)}><X size={14} /></button>
        </div>
      ))}
      {count < 4 && <button type="button" className="photo-add" onClick={() => onChange(count + 1)}><Camera size={22} />Add photo</button>}
    </div>
  );
}

function IntakeField({ field, value, onChange }) {
  const id = `f-${field.key}`;
  const unit = (v) => (v === 1 && field.unit1 ? field.unit1 : field.unit);
  const list = Array.isArray(value) ? value : [];
  return (
    <div className="field" role="group" aria-labelledby={id}>
      <span className="label" id={id}>{field.label}</span>
      {field.hint && <span className="hint">{field.hint}</span>}
      {field.type === "choice" && (
        <div className="stack" style={{ "--g": "8px" }}>
          {field.options.map((o) => <Choice key={o.value} on={value === o.value} onClick={() => onChange(o.value)} label={o.label} hint={o.hint} />)}
        </div>
      )}
      {field.type === "chips" && (
        <div className="chips">{field.options.map((o) => <Chip key={o.value} on={value === o.value} onClick={() => onChange(o.value)}>{o.label}</Chip>)}</div>
      )}
      {field.type === "multi" && (
        <div className="chips">
          {field.options.map((o) => {
            const on = list.includes(o.value);
            return <Chip key={o.value} on={on} onClick={() => onChange(on ? list.filter((v) => v !== o.value) : [...list, o.value])}>{on && <Check size={15} strokeWidth={3} />}{o.label}</Chip>;
          })}
        </div>
      )}
      {field.type === "number" && (
        <Stepper value={value} onChange={onChange} min={field.min} max={field.max} step={field.step} label={field.label} format={(v) => `${v} ${unit(v)}`} />
      )}
      {field.type === "counts" && (
        <div className="card flat" style={{ padding: "2px 16px" }}>
          {field.items.map((it) => (
            <div key={it.key} className="list-row">
              <div className="grow stack" style={{ "--g": "0px" }}><b>{it.label}</b>{it.hint && <span className="xs muted">{it.hint}</span>}</div>
              <Stepper compact value={value[it.key] || 0} onChange={(n) => onChange({ ...value, [it.key]: n })} min={0} max={10} label={it.label} />
            </div>
          ))}
        </div>
      )}
      {field.type === "text" && (
        <textarea className="input" value={value} onChange={(e) => onChange(e.target.value)} placeholder={field.placeholder} aria-labelledby={id} />
      )}
      {field.type === "photos" && <PhotoPicker count={value} onChange={onChange} />}
    </div>
  );
}

function DetailsScreen({ cat, quote, setQuote, go, steps, answers, setAnswer }) {
  const emptyCounts = cat.intake.find((f) => f.type === "counts" && Object.values(answers[f.key] || {}).every((n) => !n));
  return (
    <div className="c-flow">
      <FlowTop steps={steps} current="details" onBack={() => go(cat.measure ? "measure" : "landing")} />
      <div className="stack" style={{ "--g": "8px" }}>
        <span className="kicker">{cat.name}</span>
        <h1 className="h1">A few quick questions</h1>
        <p className="muted">So the price reflects the real job, and nobody turns up surprised.</p>
      </div>
      {cat.intake.map((f) => <IntakeField key={f.key} field={f} value={answers[f.key]} onChange={(v) => setAnswer(f.key, v)} />)}
      <label className="field">
        <span className="label">Anything else they should know? <span className="muted" style={{ fontWeight: 400 }}>(optional)</span></span>
        <textarea className="input" value={quote.notes} onChange={(e) => setQuote((q) => ({ ...q, notes: e.target.value }))}
          placeholder={cat.group === "outside" ? "For example: the side gate sticks, so please close it behind you." : "For example: parking is on the drive, and the cat mustn't get out."} />
      </label>
      <button type="button" className="btn btn-cta btn-lg btn-block" disabled={!!emptyCounts} onClick={() => go("price")}>See my price</button>
      {emptyCounts && <p className="small center" style={{ color: "var(--danger)" }}>Add at least one item to see a price.</p>}
    </div>
  );
}

const CONFIDENCE = {
  high: [3, "Usually close", "Most providers accept prices like this as they are."],
  medium: [2, "Fairly close", "Some providers adjust the price once they see the details."],
  low: [1, "A rough starting point", "Jobs like this vary a lot. Most providers will look at your photos or description and suggest their own price."],
};

function PriceScreen({ cat, est, quote, setQuote, go, steps }) {
  const { provider, fee } = split(est.price);
  const low = Math.round(est.price * est.spread[0]);
  const high = Math.round(est.price * est.spread[1]);
  const [bars, confLabel, confDefault] = CONFIDENCE[est.confidence];
  const setWhen = (k, v) => setQuote((q) => ({ ...q, when: { ...q.when, [k]: v } }));
  return (
    <div className="c-flow">
      <FlowTop steps={steps} current="price" onBack={() => go("details")} />
      <div className="card stack" style={{ "--g": "16px" }}>
        <span className="kicker">Your guide price for {cat.name.toLowerCase()}</span>
        <div className="row wrap" style={{ alignItems: "baseline", "--g": "12px" }}>
          <span className="price-big">{fmt(est.price)}</span>
          <span className="muted" style={{ fontSize: 18 }}>{est.unit}</span>
        </div>
        {est.first && (
          <div className="soft small"><b>First visit {fmt(est.first)}.</b> {est.firstReason} After that it's {fmt(est.price)} {est.unit}.</div>
        )}
        <p className="muted">Jobs like yours usually go for {fmt(low)} to {fmt(high)}, and take about {fmtDuration(est.mins)}.</p>
        {est.note && <p className="small row top" style={{ "--g": "8px" }}><Info size={16} style={{ flex: "none", marginTop: 2 }} /> {est.note}</p>}
        <div className="row" style={{ "--g": "12px" }}>
          <span className="conf" aria-hidden="true">{[1, 2, 3].map((n) => <i key={n} className={n <= bars ? "on" : ""} />)}</span>
          <span className="small"><b>{confLabel}.</b> <span className="muted">{est.confNote || confDefault}</span></span>
        </div>
        <hr />
        <div className="stack" style={{ "--g": "8px" }}>
          <div className="row between"><span className="row" style={{ "--g": "8px" }}><span className="dot dot-provider" /> Goes to your provider</span><b>{fmt(provider)}</b></div>
          <div className="row between"><span className="row" style={{ "--g": "8px" }}><span className="dot dot-fee" /> {BRAND} fee ({pct(TAKE_RATE)})</span><b>{fmt(fee)}</b></div>
        </div>
      </div>

      <div className="card flat stack" style={{ "--g": "14px" }}>
        <h2 className="h3">How the guide price works</h2>
        {[
          "Checked providers near you see your job and this price.",
          "They can accept it, or suggest a different price with a reason.",
          "If someone accepts the guide price, you're booked. If they suggest another price, you decide.",
        ].map((t, i) => (
          <div key={i} className="num-item"><span className="n">{i + 1}</span><span>{t}</span></div>
        ))}
      </div>

      <div className="stack" style={{ "--g": "10px" }}>
        <span className="label">When suits you?</span>
        <div className="chips">
          {[["any", "Any day"], ["weekdays", "Weekdays"], ["weekends", "Weekends"]].map(([v, l]) => <Chip key={v} on={quote.when.days === v} onClick={() => setWhen("days", v)}>{l}</Chip>)}
        </div>
        <div className="chips">
          {[["morning", "Mornings"], ["afternoon", "Afternoons"], ["either", "Either"]].map(([v, l]) => <Chip key={v} on={quote.when.time === v} onClick={() => setWhen("time", v)}>{l}</Chip>)}
        </div>
      </div>

      <div className="stack" style={{ "--g": "10px" }}>
        <button type="button" className="btn btn-cta btn-lg btn-block" onClick={() => go("contact")}>Request this job</button>
        <p className="xs muted center">Requesting is free. Nothing is charged until the work is done.</p>
      </div>
    </div>
  );
}

function ContactScreen({ cat, est, quote, setQuote, go, steps }) {
  const [agree, setAgree] = useState(false);
  const set = (k) => (e) => setQuote((q) => ({ ...q, contact: { ...q.contact, [k]: e.target.value } }));
  const c = quote.contact;
  const valid = c.name.trim() && c.phone.trim() && agree;
  return (
    <div className="c-flow">
      <FlowTop steps={steps} current="contact" onBack={() => go("price")} />
      <div className="soft row between small">
        <span className="row" style={{ "--g": "8px" }}><CatIcon id={cat.id} size={18} /> {cat.name}</span>
        <b>{fmt(est.price)} {est.unit}</b>
      </div>
      <div className="stack" style={{ "--g": "8px" }}>
        <h1 className="h1">Where should we send updates?</h1>
        <p className="muted">We'll text you when someone local picks up your job. No password: we send a code whenever you sign in.</p>
      </div>
      <label className="field"><span className="label">Your name</span><input className="input" value={c.name} onChange={set("name")} autoComplete="name" /></label>
      <label className="field"><span className="label">Mobile number</span><input className="input" value={c.phone} onChange={set("phone")} inputMode="tel" autoComplete="tel" /></label>
      <label className="field"><span className="label">Email <span className="muted" style={{ fontWeight: 400 }}>(for receipts)</span></span><input className="input" value={c.email} onChange={set("email")} inputMode="email" autoComplete="email" /></label>
      <div className="field">
        <span className="label">Payment card</span>
        <div className="card-mock"><CreditCard size={18} /><span className="grow">•••• •••• •••• 4242</span><span className="muted">12/28</span></div>
        <span className="hint row" style={{ "--g": "6px" }}><Lock size={13} /> Held securely by Stripe. Charged only after each visit is done.</span>
      </div>
      <div className="card flat stack" style={{ "--g": "12px" }}>
        <CheckRow on={agree} onChange={setAgree}>
          I agree to the customer terms. My agreement for the work is with the provider who takes the job, and {BRAND} acts as their booking and payment agent.
        </CheckRow>
      </div>
      <p className="small muted">Your number isn't shared with providers. You message each other through {BRAND}, so there's a record if anything needs sorting out.</p>
      <button type="button" className="btn btn-cta btn-lg btn-block" disabled={!valid}
        onClick={() => { setQuote((q) => ({ ...q, booking: null })); go("offers"); }}>Send my request</button>
      {!agree && <p className="xs muted center">Tick the box above to send your request.</p>}
    </div>
  );
}

function OffersScreen({ cat, est, quote, setQuote, go }) {
  const [events, setEvents] = useState([]);
  const [declined, setDeclined] = useState(false);
  const [run, setRun] = useState(0);
  const bookedRef = useRef(false);
  const district = (quote.address.match(/\b([A-Z]{1,2}\d{1,2})\s?\d[A-Z]{2}\b/i) || [])[1]?.toUpperCase() || "you";
  const pool = providersFor(cat.id);
  const accepter = pool[0] || PROVIDERS[0];
  const counterer = pool[1];
  const counter = Math.round(est.price * 1.2);
  const script = [
    { t: 600, kind: "sent", text: `Sent to checked ${cat.short.toLowerCase()} providers near ${district}` },
    { t: 2100, kind: "view", text: counterer ? `${counterer.short} and one other are looking at your job` : "Two providers are looking at your job" },
    ...(counterer ? [{ t: 3700, kind: "counter", who: counterer.id, price: counter }] : []),
    { t: 6600, kind: "accept", who: accepter.id, price: est.price },
  ];

  useEffect(() => {
    if (quote.booking) { bookedRef.current = true; setEvents(script); return undefined; }
    bookedRef.current = false;
    setEvents([]);
    setDeclined(false);
    const ids = script.map((ev) => setTimeout(() => {
      if (bookedRef.current) return;
      setEvents((e) => [...e, ev]);
      if (ev.kind === "accept") {
        bookedRef.current = true;
        setQuote((q) => ({ ...q, booking: { providerId: ev.who, price: ev.price, via: "guide" } }));
      }
    }, ev.t));
    return () => ids.forEach(clearTimeout);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run]);

  const acceptCounter = (ev) => {
    bookedRef.current = true;
    setQuote((q) => ({ ...q, booking: { providerId: ev.who, price: ev.price, via: "counter" } }));
  };
  const replay = () => { setQuote((q) => ({ ...q, booking: null })); setRun((r) => r + 1); };
  const booking = quote.booking;
  const p = booking && providerById(booking.providerId);

  return (
    <div className="c-flow">
      {!booking ? (
        <div className="card stack" style={{ "--g": "10px" }} aria-live="polite">
          <div className="row" style={{ "--g": "14px" }}><span className="pulse" /><h1 className="h2">Finding someone local</h1></div>
          <p className="muted">Most jobs near {district} are picked up within the hour. We'll text you as soon as it's booked, so you can close this page.</p>
        </div>
      ) : (
        <div className="card stack" style={{ "--g": "16px" }} aria-live="polite">
          <div className="row" style={{ "--g": "14px" }}>
            <span className="success-mark sm"><Check size={22} strokeWidth={3} /></span>
            <div className="stack" style={{ "--g": "2px" }}>
              <h1 className="h2">You're booked with {p.short}</h1>
              <span className="small muted">{booking.via === "guide" ? `They accepted your guide price of ${fmt(booking.price)}.` : `You accepted ${fmt(booking.price)}.`}</span>
            </div>
          </div>
          <button type="button" className="btn btn-cta btn-lg btn-block" onClick={() => go("booked")}>See your booking</button>
        </div>
      )}

      <div className="stack" style={{ "--g": "14px" }}>
        <h2 className="h3">What's happened so far</h2>
        <div>
          {events.map((ev, i) => {
            if (ev.kind === "counter") {
              const cp = providerById(ev.who);
              const tookIt = booking?.via === "counter";
              return (
                <div key={i} className="tl-item">
                  <span className="tl-ico alert"><PoundSterling size={16} /></span>
                  <div className="grow stack" style={{ "--g": "8px" }}>
                    <span><b>{cp.short} suggested {fmt(ev.price)}</b> <span className="muted">instead of {fmt(est.price)}</span></span>
                    <span className="small muted">"From the description it'll take a bit longer than the estimate. This covers the extra time."</span>
                    {!booking && !declined && (
                      <div className="row wrap" style={{ "--g": "8px" }}>
                        <button type="button" className="btn btn-primary btn-sm" onClick={() => acceptCounter(ev)}>Accept {fmt(ev.price)}</button>
                        <button type="button" className="btn btn-ghost btn-sm" onClick={() => setDeclined(true)}>Keep waiting</button>
                      </div>
                    )}
                    {declined && !booking && <span className="xs muted">You're waiting for someone at the guide price.</span>}
                    {tookIt && <span className="badge ok" style={{ alignSelf: "flex-start" }}><Check size={12} /> You accepted this</span>}
                  </div>
                </div>
              );
            }
            const Icon = ev.kind === "sent" ? Send : ev.kind === "view" ? Users : Check;
            const pv = ev.kind === "accept" ? providerById(ev.who) : null;
            return (
              <div key={i} className="tl-item">
                <span className={"tl-ico" + (ev.kind === "accept" ? " good" : "")}><Icon size={16} /></span>
                <div className="grow stack" style={{ "--g": "2px", paddingTop: 5 }}>
                  {pv ? <b>{pv.short} accepted your guide price</b> : <span>{ev.text}</span>}
                  {pv && <span className="small muted">Rated {pv.rating} from {pv.reviews} jobs, and lives {pv.miles} miles away</span>}
                </div>
              </div>
            );
          })}
        </div>
      </div>
      <div className="row between xs muted">
        <span>Prototype: provider responses are simulated.</span>
        <button type="button" className="btn btn-link small" onClick={replay}>Replay</button>
      </div>
    </div>
  );
}

function BookedScreen({ cat, est, quote, setQuote, go }) {
  const fallback = providersFor(cat.id)[0] || PROVIDERS[0];
  const b = quote.booking || { providerId: fallback.id, price: est.price, via: "guide" };
  const p = providerById(b.providerId);
  const { provider, fee } = split(b.price);
  const who = firstName(p.name);
  const answers = quote.answers[cat.id];
  const recurring = isRecurring(cat, answers);
  const time = { morning: "morning, 8am to 12pm", afternoon: "afternoon, 12pm to 5pm", either: "time confirmed the day before" }[quote.when.time];
  const freq = optionLabel(cat, "frequency", answers.frequency);
  const insuredTo = p.insurance.expires ? p.insurance.expires.split(" ").slice(1).join(" ") : "";
  return (
    <div className="c-flow">
      <div className="stack center" style={{ "--g": "12px", alignItems: "center", paddingTop: 8 }}>
        <span className="success-mark"><Check size={32} strokeWidth={3} /></span>
        <h1 className="h1">You're booked</h1>
        <p className="muted">We've texted the details to {quote.contact.phone}.</p>
      </div>
      <div className="card stack" style={{ "--g": "16px" }}>
        <div className="row" style={{ "--g": "14px" }}>
          <Avatar initials={p.initials} size={56} />
          <div className="grow stack" style={{ "--g": "4px" }}>
            <h2 className="h3">{p.short}</h2>
            <span className="row small muted" style={{ "--g": "6px" }}><Stars value={p.rating} size={14} /> {p.rating} from {p.reviews} jobs</span>
          </div>
        </div>
        <div className="row wrap" style={{ "--g": "6px" }}>
          <span className="badge ok"><BadgeCheck size={13} /> ID checked</span>
          {cat.requires.includes("dbs_basic") && <span className="badge ok"><ShieldCheck size={13} /> Basic DBS checked</span>}
          <span className="badge ok"><ShieldCheck size={13} /> Insured until {insuredTo}</span>
          <span className="badge"><MapPin size={13} /> Lives {p.miles} miles away</span>
        </div>
        <hr />
        <dl className="kv">
          <dt>Job</dt><dd>{cat.name}{recurring && freq ? `, ${freq.toLowerCase()}` : ""}</dd>
          <dt>{recurring ? "First visit" : "When"}</dt><dd>Tuesday 29 September, {time}</dd>
          <dt>Price</dt><dd>{fmt(b.price)} {est.unit}, charged after {recurring ? "each visit" : "the job"}</dd>
          <dt>Split</dt><dd>{fmt(provider)} to {who}, {fmt(fee)} {BRAND} fee</dd>
        </dl>
      </div>
      <div className="soft small stack" style={{ "--g": "6px" }}>
        <b>Who you're dealing with</b>
        <span>Your agreement for this job is with {who}. {BRAND} arranged it, takes payment on their behalf through Stripe, and helps sort things out if anything goes wrong.</span>
      </div>
      <div className="grid2">
        <button type="button" className="btn btn-ghost" onClick={() => { setQuote((q) => ({ ...q, accountTab: "messages" })); go("account"); }}><MessageCircle size={17} /> Message {who}</button>
        <button type="button" className="btn btn-primary" onClick={() => { setQuote((q) => ({ ...q, accountTab: "visits" })); go("account"); }}>My account</button>
      </div>
    </div>
  );
}

function AccountScreen({ cat, est, quote, go }) {
  const notify = useToast();
  const [tab, setTab] = useState(quote.accountTab || "visits");
  const [pause, setPause] = useState(true);
  const [cover, setCover] = useState(true);
  const [draft, setDraft] = useState("");
  const fallback = providersFor(cat.id)[0] || PROVIDERS[0];
  const b = quote.booking || { providerId: fallback.id, price: est.price };
  const p = providerById(b.providerId);
  const who = firstName(p.name);
  const answers = quote.answers[cat.id];
  const recurring = isRecurring(cat, answers);
  const freq = optionLabel(cat, "frequency", answers.frequency);
  const outside = cat.group === "outside";
  const [thread, setThread] = useState(outside ? [
    { me: false, text: `Hi, it's ${who}. I'll be with you Tuesday about 10:30. Is the side gate the best way in?` },
    { me: true, text: "Yes, it's unlocked. It sticks a bit, so give it a shove!" },
    { me: false, text: "No problem. See you then." },
  ] : [
    { me: false, text: `Hi, it's ${who}. I'll be with you Tuesday about 10:30. Will someone be in, or is there a key safe?` },
    { me: true, text: "I'll be in. You can park on the drive." },
    { me: false, text: "Lovely, see you then." },
  ]);
  useEffect(() => setTab(quote.accountTab || "visits"), [quote.accountTab]);
  const send = () => {
    if (!draft.trim()) return;
    setThread((t) => [...t, { me: true, text: draft.trim() }]);
    setDraft("");
  };
  const upcoming = recurring ? [["Tue", 29, "Sep"], ["Tue", 13, "Oct"], ["Tue", 27, "Oct"]] : [["Tue", 29, "Sep"]];
  return (
    <div className="c-flow wide">
      <div className="stack" style={{ "--g": "4px" }}>
        <span className="muted">Welcome back</span>
        <h1 className="h1">Hi {firstName(quote.contact.name)}</h1>
      </div>
      <div className="card stack" style={{ "--g": "14px" }}>
        <div className="row top" style={{ "--g": "14px" }}>
          <span className="cat-ico lg"><CatIcon id={cat.id} size={24} /></span>
          <div className="grow stack" style={{ "--g": "2px" }}>
            <span className="small muted">{recurring ? "Next visit" : "Booked"}</span>
            <h2 className="h2">Tuesday 29 September, morning</h2>
            <span className="muted">{cat.name} with {p.short}, {fmt(b.price)}</span>
          </div>
        </div>
        <div className="row wrap" style={{ "--g": "8px" }}>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => notify(recurring ? "Visit skipped. Your next one is Tuesday 13 October." : "Pick a new date and we'll check with them")}>{recurring ? "Skip this visit" : "Change the date"}</button>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setTab("messages")}><MessageCircle size={15} /> Message {who}</button>
        </div>
      </div>

      <div className="tabs" role="tablist">
        {[["visits", "Visits"], ["plan", "Plan"], ["messages", "Messages"]].map(([v, l]) => (
          <button key={v} type="button" role="tab" aria-selected={tab === v} className={tab === v ? "on" : ""} onClick={() => setTab(v)}>{l}</button>
        ))}
      </div>

      {tab === "visits" && (
        <div className="stack" style={{ "--g": "18px" }}>
          <div className="card flat" style={{ padding: "4px 18px" }}>
            {upcoming.map(([dow, d, m]) => (
              <div key={d} className="list-row">
                <div className="date-chip"><span>{dow}</span><b>{d}</b></div>
                <div className="grow stack" style={{ "--g": "0px" }}><b>{cat.name}</b><span className="small muted">{p.short}, {m === "Sep" ? "booked" : "planned"}</span></div>
                <span className="small">{fmt(b.price)}</span>
              </div>
            ))}
          </div>
          <h2 className="h3">Done</h2>
          <div className="card flat" style={{ padding: "4px 18px" }}>
            <div className="list-row">
              <span className="thumb" aria-hidden="true" />
              <div className="grow stack" style={{ "--g": "0px" }}><b>Tuesday 15 September</b><span className="small muted">Took {fmtDuration(est.mins)}, after photo added</span></div>
              <button type="button" className="btn btn-primary btn-sm" onClick={() => go("rate")}>Rate</button>
            </div>
            <div className="list-row">
              <span className="thumb" aria-hidden="true" />
              <div className="grow stack" style={{ "--g": "0px" }}><b>Tuesday 1 September</b><span className="small muted">Rated 5 stars</span></div>
              <Stars value={5} size={14} />
            </div>
          </div>
        </div>
      )}

      {tab === "plan" && (recurring ? (
        <div className="card stack" style={{ "--g": "4px" }}>
          <div className="row between" style={{ paddingBottom: 10 }}>
            <div className="stack" style={{ "--g": "2px" }}><h2 className="h3">{cat.name}, {freq?.toLowerCase()}</h2><span className="small muted">with {p.short}</span></div>
            <b>{fmt(b.price)} {est.unit}</b>
          </div>
          <hr />
          {outside
            ? <Toggle on={pause} onChange={setPause} label="Pause over winter" hint="No visits November to February. We restart your plan in March, nothing to remember." />
            : <Toggle on={pause} onChange={setPause} label="Pause while I'm away" hint="Tell us your dates and those visits are skipped automatically." />}
          <hr />
          <Toggle on={cover} onChange={setCover} label={`Cover when ${who}'s away`} hint={`We'll offer the visit to another checked local provider at the same price. ${who} carries on afterwards.`} />
          <hr />
          <div className="row wrap" style={{ "--g": "10px", paddingTop: 12 }}>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => notify("You can change how often in the full app.")}>Change how often</button>
            <button type="button" className="btn btn-link small" style={{ color: "var(--danger)" }} onClick={() => notify("Cancelling is one tap, with no fee.")}>Cancel plan</button>
          </div>
        </div>
      ) : (
        <div className="card stack" style={{ "--g": "12px" }}>
          <h2 className="h3">No regular plan</h2>
          <p className="small muted">This was a one-off. You can book {who} again at the same price in one tap.</p>
          <button type="button" className="btn btn-primary btn-sm" style={{ alignSelf: "flex-start" }} onClick={() => notify(`Request sent to ${who}`)}>Book {who} again</button>
        </div>
      ))}

      {tab === "messages" && (
        <div className="card stack" style={{ "--g": "10px" }}>
          <div className="row" style={{ "--g": "10px", paddingBottom: 6 }}><Avatar initials={p.initials} size={36} /><b>{p.short}</b></div>
          {thread.map((m, i) => (
            <div key={i} className={"bubble-row" + (m.me ? " me" : "")}><div className="msg">{m.text}</div></div>
          ))}
          <div className="row" style={{ "--g": "8px", paddingTop: 6 }}>
            <input className="input grow" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder={`Message ${who}`}
              onKeyDown={(e) => { if (e.key === "Enter") send(); }} aria-label={`Message ${who}`} />
            <button type="button" className="btn btn-primary" onClick={send} aria-label="Send"><Send size={18} /></button>
          </div>
          <p className="xs muted">Messages stay in {BRAND}, so there's a record if anything needs sorting out.</p>
        </div>
      )}
    </div>
  );
}

function AfterPhoto() {
  return (
    <svg viewBox="0 0 400 170" className="chart" role="img" aria-label="After photo of the mown lawn">
      <rect width="400" height="170" style={{ fill: "var(--sky)" }} />
      {Array.from({ length: 12 }).map((_, i) => (
        <rect key={i} x={i * 34 - 10} y="52" width="34" height="118" style={{ fill: i % 2 ? "var(--lawn-1)" : "var(--lawn-2)" }} />
      ))}
      {[20, 70, 120, 170, 220, 270, 320, 370].map((cx, i) => <circle key={i} cx={cx} cy={40 + (i % 2) * 6} r={32} style={{ fill: "var(--hedge)" }} />)}
      <rect x="0" y="150" width="400" height="20" style={{ fill: "var(--path)" }} />
    </svg>
  );
}

function RateScreen({ cat, est, quote, go }) {
  const notify = useToast();
  const fallback = providersFor(cat.id)[0] || PROVIDERS[0];
  const p = providerById(quote.booking?.providerId || fallback.id);
  const who = firstName(p.name);
  const [stars, setStars] = useState(0);
  const [tags, setTags] = useState([]);
  const [tip, setTip] = useState(0);
  const [problem, setProblem] = useState(false);
  const [done, setDone] = useState(false);
  const words = ["", "Poor", "Not great", "OK", "Good", "Excellent"];
  const good = ["On time", "Thorough", "Friendly", "Left it tidy"];
  const bad = ["Missed bits", "Late", "Left a mess", "Rushed"];
  const toggleTag = (t) => setTags((x) => (x.includes(t) ? x.filter((y) => y !== t) : [...x, t]));

  if (done) {
    return (
      <div className="c-flow">
        <div className="stack center" style={{ "--g": "14px", alignItems: "center", paddingTop: 24 }}>
          <span className="success-mark"><Check size={32} strokeWidth={3} /></span>
          <h1 className="h1">Thanks for rating {who}</h1>
          <p className="muted">{tip ? `Your ${fmt(tip)} tip goes straight to ${who}.` : `${who} will see your rating.`}</p>
          <button type="button" className="btn btn-primary btn-lg" onClick={() => go("account")}>Back to my account</button>
        </div>
      </div>
    );
  }
  return (
    <div className="c-flow">
      <button type="button" className="btn btn-link" style={{ alignSelf: "flex-start" }} onClick={() => go("account")}><ArrowLeft size={18} /> My account</button>
      <h1 className="h1">How did {who} do?</h1>
      <div className="card flat" style={{ padding: 0, overflow: "hidden" }}>
        {cat.group === "outside" ? <AfterPhoto /> : cat.group === "inside" ? <RoomPhoto /> : null}
        <div className="row between wrap small" style={{ padding: "12px 16px" }}>
          <span><b>{cat.name}, Tuesday 15 September.</b> <span className="muted">Took {fmtDuration(est.mins)}.</span></span>
          {cat.group !== "help" && <span className="badge ok"><Camera size={12} /> After photo</span>}
        </div>
      </div>
      <div className="stack center" style={{ "--g": "4px", alignItems: "center" }}>
        <Stars value={stars} onChange={setStars} size={38} />
        <span className="small muted" aria-live="polite">{words[stars] || "Tap a star"}</span>
      </div>
      {stars > 0 && (
        <div className="stack" style={{ "--g": "10px" }}>
          <span className="label">{stars >= 4 ? "What went well?" : "What went wrong?"}</span>
          <div className="chips">{(stars >= 4 ? good : bad).map((t) => <Chip key={t} on={tags.includes(t)} onClick={() => toggleTag(t)}>{t}</Chip>)}</div>
        </div>
      )}
      <div className="stack" style={{ "--g": "10px" }}>
        <span className="label">Add a tip? <span className="muted" style={{ fontWeight: 400 }}>All of it goes to {who}.</span></span>
        <div className="chips">{[0, 2, 5, 10].map((t) => <Chip key={t} on={tip === t} onClick={() => setTip(t)}>{t ? fmt(t) : "No tip"}</Chip>)}</div>
      </div>
      <button type="button" className="btn btn-cta btn-lg btn-block" disabled={!stars} onClick={() => setDone(true)}>Send rating</button>
      <button type="button" className="btn btn-link" style={{ alignSelf: "center" }} onClick={() => setProblem((v) => !v)}>Something not right?</button>
      {problem && (
        <div className="card flat stack" style={{ "--g": "12px" }}>
          <h2 className="h3">Tell us what happened</h2>
          <p className="small muted">We'll share it with {who} and help you agree a fix, usually a free return visit. Please let us know within 48 hours of the visit.</p>
          <textarea className="input" placeholder="For example: the bathroom floor wasn't done." aria-label="What happened" />
          <PhotoPicker count={0} onChange={() => notify("Photo added")} />
          <button type="button" className="btn btn-primary btn-block" onClick={() => { setProblem(false); notify(`Reported. We've let ${who} know and will text you within a day.`); }}>Report the problem</button>
        </div>
      )}
    </div>
  );
}

function WhatWeDontDo() {
  return (
    <section className="c-section">
      <div className="card flat stack" style={{ "--g": "18px" }}>
        <div className="stack" style={{ "--g": "4px" }}>
          <h2 className="h2">What we don't do</h2>
          <p className="muted">Some jobs need a registered or licensed professional. We don't list them, so you're never matched with the wrong person.</p>
        </div>
        <div className="excluded">
          {EXCLUDED.map((x) => (
            <div key={x.name} className="ex-row">
              <span className="ex-ico"><Ban size={15} /></span>
              <div className="stack" style={{ "--g": "0px" }}><b className="small">{x.name}</b><span className="xs muted">Use {x.instead}.</span></div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function RoomPhoto() {
  const f = (v) => ({ fill: `var(${v})` });
  return (
    <svg viewBox="0 0 400 170" className="chart" role="img" aria-label="After photo of a clean living room">
      <rect width="400" height="118" style={f("--sky")} />
      <rect y="118" width="400" height="52" style={f("--path")} />
      <rect x="40" y="26" width="92" height="66" rx="4" style={{ ...f("--surface"), stroke: "var(--hedge)", strokeWidth: 4 }} />
      <line x1="86" y1="26" x2="86" y2="92" style={{ stroke: "var(--hedge)", strokeWidth: 3 }} />
      <rect x="190" y="78" width="160" height="50" rx="12" style={f("--primary")} />
      <rect x="182" y="66" width="26" height="62" rx="10" style={f("--primary")} />
      <rect x="332" y="66" width="26" height="62" rx="10" style={f("--primary")} />
      <rect x="214" y="70" width="44" height="24" rx="8" style={f("--accent")} />
      <rect x="150" y="96" width="18" height="30" rx="3" style={f("--hedge")} />
      <circle cx="159" cy="86" r="16" style={f("--lawn-1")} />
    </svg>
  );
}

function InviteScreen({ go }) {
  const dave = providerById("dave");
  const price = 25;
  const { fee } = splitOwn(price);
  const [agree, setAgree] = useState(false);
  const [done, setDone] = useState(false);
  const perks = [
    [CreditCard, "Pay by card after each visit", "No more cash or bank transfers."],
    [Bell, "A text the day before", "So you know when Dave's coming."],
    [Camera, "A photo when it's done", "Handy if you're out."],
    [Receipt, "A receipt for every visit", "All in one place."],
    [Users, "Cover if Dave's away", "Only if you want it. Dave carries on afterwards."],
  ];
  if (done) {
    return (
      <div className="c-flow">
        <div className="stack center" style={{ "--g": "14px", alignItems: "center", paddingTop: 24 }}>
          <span className="success-mark"><Check size={32} strokeWidth={3} /></span>
          <h1 className="h1">You're all set, Mary</h1>
          <p className="muted">Dave's next visit is Tuesday 29 September. You'll pay by card after each visit.</p>
          <button type="button" className="btn btn-primary btn-lg" onClick={() => go("landing")}>Done</button>
        </div>
      </div>
    );
  }
  return (
    <div className="c-flow">
      <div className="card stack center" style={{ "--g": "12px", alignItems: "center" }}>
        <Avatar initials={dave.initials} size={64} />
        <h1 className="h1">Dave has invited you to {BRAND}</h1>
        <p className="muted">Hi Mary. Dave would like to arrange your visits through {BRAND} from now on.</p>
      </div>
      <div className="card flat">
        <dl className="kv">
          <dt>Job</dt><dd>Lawn mowing, every 2 weeks</dd>
          <dt>Price</dt><dd>{fmt(price)} a visit, set by Dave</dd>
          <dt>Next visit</dt><dd>Tuesday 29 September</dd>
        </dl>
      </div>
      <div className="card flat stack" style={{ "--g": "14px" }}>
        <h2 className="h3">What changes for you</h2>
        {perks.map(([I, t, d]) => (
          <div key={t} className="check-row">
            <span className="ci"><I size={18} /></span>
            <div className="stack" style={{ "--g": "1px" }}><b>{t}</b><span className="small muted">{d}</span></div>
          </div>
        ))}
        <p className="small muted">Nothing else changes. Same Dave, same price.</p>
      </div>
      <div className="soft small">Your agreement is still with Dave. {BRAND} handles bookings and payments for him, and Dave pays us a small fee of {fmt(fee)} a visit. It isn't added to your price.</div>
      <div className="field">
        <span className="label">Payment card</span>
        <div className="card-mock"><CreditCard size={18} /><span className="grow muted">Add your card</span></div>
        <span className="hint row" style={{ "--g": "6px" }}><Lock size={13} /> Held securely by Stripe. Charged only after each visit.</span>
      </div>
      <CheckRow on={agree} onChange={setAgree}>I agree to the customer terms. My agreement for the work is with Dave, and {BRAND} acts as his booking and payment agent.</CheckRow>
      <button type="button" className="btn btn-cta btn-lg btn-block" disabled={!agree} onClick={() => setDone(true)}>Accept Dave's invite</button>
      <p className="xs muted center">You can stop using {BRAND} at any time and arrange things with Dave directly again.</p>
    </div>
  );
}

/* ============================ Provider surface ============================ */

const mmss = (ms) => {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

function ProviderApp({ screen, go }) {
  const [offerId, setOfferId] = useState(PROVIDER_OFFERS[0].id);
  const [accepted, setAccepted] = useState({});
  const [countered, setCountered] = useState({});
  const [timer, setTimer] = useState({ start: null, stoppedAt: null, extra: 0 });
  const [now, setNow] = useState(Date.now());
  const [photos, setPhotos] = useState({ before: false, after: false });
  const [limit, setLimit] = useState({ on: true, period: "week", amount: 250 });
  const bodyRef = useRef(null);
  const running = !!timer.start && !timer.stoppedAt;

  useEffect(() => { if (bodyRef.current) bodyRef.current.scrollTop = 0; }, [screen]);
  useEffect(() => {
    if (!running) return undefined;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [running]);

  const elapsed = (timer.start ? (timer.stoppedAt || now) - timer.start : 0) + timer.extra;
  const offer = PROVIDER_OFFERS.find((o) => o.id === offerId);
  const openOffer = (id) => { setOfferId(id); go("offer"); };
  const startTimer = () => { const t = Date.now(); setNow(t); setTimer({ start: t, stoppedAt: null, extra: 0 }); };
  const finishTimer = () => { setTimer((t) => ({ ...t, stoppedAt: Date.now() })); go("finish"); };
  const addTime = () => setTimer((t) => ({ ...t, extra: t.extra + 10 * 60000 }));
  const resetJob = () => { setTimer({ start: null, stoppedAt: null, extra: 0 }); setPhotos({ before: false, after: false }); };
  const earned = limit.period === "week" ? WEEK_SO_FAR : MONTH_SO_FAR;
  const remaining = limit.on ? Math.max(0, limit.amount - earned) : null;

  const tabOf = { jobs: "jobs", offer: "jobs", onjob: "today", finish: "today", earnings: "earnings", tax: "earnings", limit: "earnings", me: "me", cover: "me", mycustomers: "me" }[screen];
  const tabs = [["jobs", "Jobs", Bell, "jobs"], ["today", "Today", Route, "onjob"], ["earnings", "Earnings", Wallet, "earnings"], ["me", "Me", User, "me"]];

  return (
    <div className="p-stage">
      <div className="p-phone">
        {screen === "sms" ? <SmsScreen go={go} /> : (
          <>
            <div className="p-top">
              <span className="brand sm"><span className="brand-mark"><Sprout size={14} /></span>{BRAND}</span>
              <span className="xs muted">{screen === "onboarding" ? "Sign up" : "Dave Hughes"}</span>
            </div>
            <div className="p-body" ref={bodyRef}>
              {screen === "jobs" && <ProviderJobs openOffer={openOffer} accepted={accepted} countered={countered} limit={limit} remaining={remaining} earned={earned} go={go} />}
              {screen === "offer" && <OfferDetail key={offer.id} o={offer} go={go} accepted={accepted} setAccepted={setAccepted} countered={countered} setCountered={setCountered} remaining={remaining} limit={limit} />}
              {screen === "onjob" && <TodayScreen started={!!timer.start} elapsed={elapsed} startTimer={startTimer} finishTimer={finishTimer} addTime={addTime} photos={photos} setPhotos={setPhotos} go={go} />}
              {screen === "finish" && <FinishScreen elapsed={elapsed} go={go} resetJob={resetJob} />}
              {screen === "earnings" && <EarningsScreen go={go} limit={limit} remaining={remaining} />}
              {screen === "tax" && <TaxScreen go={go} />}
              {screen === "limit" && <LimitScreen key={JSON.stringify(limit)} limit={limit} setLimit={setLimit} go={go} />}
              {screen === "me" && <MeScreen go={go} limit={limit} />}
              {screen === "cover" && <CoverScreen go={go} />}
              {screen === "mycustomers" && <OwnCustomersScreen go={go} />}
              {screen === "onboarding" && <OnboardingScreen go={go} />}
            </div>
            {screen !== "onboarding" && (
              <nav className="p-nav" aria-label="Provider">
                {tabs.map(([id, label, I, target]) => (
                  <button key={id} type="button" className={tabOf === id ? "on" : ""} aria-current={tabOf === id ? "page" : undefined} onClick={() => go(target)}>
                    <I size={22} strokeWidth={tabOf === id ? 2.5 : 2} />{label}
                  </button>
                ))}
              </nav>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function SmsScreen({ go }) {
  const g = PROVIDER_OFFERS[0];
  const { provider } = split(g.guide);
  const open = (e) => { e.preventDefault(); go("offer"); };
  return (
    <div className="sms">
      <div className="sms-head">
        <div className="sms-av">{BRAND[0]}</div>
        <div style={{ fontSize: 13, fontWeight: 600 }}>{BRAND}</div>
        <div style={{ fontSize: 11.5, color: "#8a8a8e" }}>Text message</div>
      </div>
      <div className="sms-body">
        <div className="sms-day">Yesterday 18:02</div>
        <div className="sms-bubble">{BRAND}: Reminder, you're mowing in Widmer End on Tuesday at 9:00. Reply PAUSE to stop new job alerts for a week.</div>
        <div className="sms-day">Today 08:14</div>
        <div className="sms-bubble">
          {BRAND}: New job near you. Lawn mowing in Hazlemere (HP15), about {g.mins} minutes, every 2 weeks. Guide price {fmt(g.guide)}, you'd get {fmt(provider)}. It's 0.4 miles from your Tuesday 9:00. Take a look: <a href={`https://${LINK}/j/${g.id}`} onClick={open}>{LINK}/j/{g.id}</a>
        </div>
      </div>
      <div className="sms-foot stack" style={{ "--g": "12px" }}>
        <div className="row top small" style={{ "--g": "10px" }}>
          <Smartphone size={18} style={{ flex: "none", marginTop: 2 }} />
          <span><b>Why a text?</b> Nothing to install, it works on any phone, and it's what these providers actually read. The link opens the job already signed in.</span>
        </div>
        <button type="button" className="btn btn-cta btn-block btn-lg" onClick={() => go("offer")}>Open the job</button>
      </div>
    </div>
  );
}

function ProviderJobs({ openOffer, accepted, countered, limit, remaining, earned, go }) {
  return (
    <>
      <div className="stack" style={{ "--g": "2px" }}>
        <span className="small muted">Wednesday 23 September</span>
        <h1 className="h1">Morning, Dave</h1>
      </div>
      <div className="grid2">
        <div className="card flat stack" style={{ "--g": "4px", padding: 16 }}>
          <span className="xs muted">This week</span>
          <span className="big-num" style={{ fontSize: 30 }}>{fmt(WEEK_SO_FAR)}</span>
          <span className="xs muted">from 7 jobs</span>
        </div>
        <div className="card flat stack" style={{ "--g": "4px", padding: 16 }}>
          <span className="xs muted">Your rating</span>
          <span className="big-num" style={{ fontSize: 30 }}>4.9</span>
          <span className="xs muted">from 38 reviews</span>
        </div>
      </div>
      {limit.on && <LimitStrip limit={limit} remaining={remaining} earned={earned} onClick={() => go("limit")} />}
      <div className="row between">
        <h2 className="h2">New jobs near you</h2>
        <span className="badge accent">{PROVIDER_OFFERS.length} new</span>
      </div>
      {PROVIDER_OFFERS.map((o) => (
        <OfferCard key={o.id} o={o} onOpen={() => openOffer(o.id)}
          state={accepted[o.id] ? "accepted" : countered[o.id] ? "countered" : null}
          over={remaining != null && !accepted[o.id] && split(o.guide).provider > remaining} limit={limit} />
      ))}
      <h2 className="h2">Coming up</h2>
      <div className="card flat" style={{ padding: "4px 16px" }}>
        {UPCOMING.map((u, i) => (
          <div key={i} className="list-row">
            <div className="date-chip"><span>{u.dow}</span><b>{u.day}</b></div>
            <div className="grow stack" style={{ "--g": "0px" }}>
              <b>{u.time} in {u.where}</b>
              <span className="small muted">{catById(u.cat).name}</span>
            </div>
            <span>{fmt(u.price)}</span>
          </div>
        ))}
      </div>
    </>
  );
}

function OfferCard({ o, state, onOpen, over, limit }) {
  const cat = catById(o.cat);
  const { provider } = split(o.guide);
  return (
    <div className="offer-card" role="button" tabIndex={0} onClick={onOpen} style={{ opacity: over ? 0.72 : 1 }}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onOpen(); } }}
      aria-label={`${cat.name} in ${o.where}, guide price ${fmt(o.guide)}`}>
      <div className="row top" style={{ width: "100%" }}>
        <span className="cat-ico"><CatIcon id={o.cat} /></span>
        <div className="grow stack" style={{ "--g": "2px" }}>
          <b>{cat.name}</b>
          <span className="small muted">{o.where}, {o.miles} miles away</span>
        </div>
        <div className="stack" style={{ "--g": "0px", textAlign: "right" }}>
          <span className="big-num" style={{ fontSize: 24 }}>{fmt(o.guide)}</span>
          <span className="xs muted">you get {fmt(provider)}</span>
        </div>
      </div>
      <div className="row wrap" style={{ "--g": "6px" }}>
        <span className="badge"><Clock size={13} /> About {o.mins} min</span>
        <span className="badge"><Calendar size={13} /> {o.freq}</span>
        {state === "accepted" && <span className="badge ok"><Check size={13} /> Yours</span>}
        {state === "countered" && <span className="badge warn">Waiting on your price</span>}
        {over && <span className="badge warn"><PiggyBank size={13} /> Over your {limit.period === "week" ? "weekly" : "monthly"} limit</span>}
      </div>
      {o.route && <span className="route-tag"><Route size={15} /> {o.route}</span>}
      <span className="xs muted">Posted {o.posted}</span>
    </div>
  );
}

function ApproxMap() {
  const road = (w) => ({ fill: "none", stroke: "var(--surface)", strokeWidth: w, strokeLinecap: "round" });
  return (
    <div className="card flat" style={{ padding: 0, overflow: "hidden" }}>
      <svg viewBox="0 0 360 150" className="chart" role="img" aria-label="Approximate area of the job">
        <rect width="360" height="150" style={{ fill: "var(--soft)" }} />
        <path d="M-10 112 C 80 92, 140 132, 220 98 S 330 62, 380 72" style={road(14)} />
        <path d="M120 -10 C 130 40, 110 90, 150 160" style={road(10)} />
        <path d="M252 -10 L 272 160" style={road(8)} />
        <circle cx="198" cy="82" r="42" style={{ fill: "var(--primary)", opacity: 0.14 }} />
        <circle cx="198" cy="82" r="42" style={{ fill: "none", stroke: "var(--primary)", strokeWidth: 2, strokeDasharray: "5 5" }} />
        <circle cx="262" cy="44" r="7" style={{ fill: "var(--accent)", stroke: "var(--ink)", strokeWidth: 1.5 }} />
        <text x="274" y="40" className="chart-val">Your 9:00</text>
      </svg>
      <div className="row xs muted" style={{ padding: "10px 14px", "--g": "6px" }}><Lock size={13} /> Exact address shown once the job is yours</div>
    </div>
  );
}

function OfferDetail({ o, go, accepted, setAccepted, countered, setCountered, remaining, limit }) {
  const cat = catById(o.cat);
  const { provider } = split(o.guide);
  const cust = firstName(o.customer.name);
  const [open, setOpen] = useState(false);
  const [price, setPrice] = useState(Math.round(o.guide * 1.2));
  const [reasons, setReasons] = useState([]);
  const REASONS = ["Longer grass than described", "Tricky access", "More waste than described", "Further than I usually go"];
  const toggle = (r) => setReasons((x) => (x.includes(r) ? x.filter((y) => y !== r) : [...x, r]));
  const sent = countered[o.id];

  return (
    <>
      <button type="button" className="btn btn-link" style={{ alignSelf: "flex-start" }} onClick={() => go("jobs")}><ArrowLeft size={18} /> All jobs</button>
      <div className="row" style={{ "--g": "14px" }}>
        <span className="cat-ico lg"><CatIcon id={o.cat} size={26} /></span>
        <div className="stack" style={{ "--g": "2px" }}>
          <h1 className="h2">{cat.name}</h1>
          <span className="small muted">{o.freq}, {o.where}</span>
        </div>
      </div>
      <ApproxMap />
      {o.route && (
        <div className="card flat row top" style={{ background: "var(--accent-soft)", borderColor: "transparent", "--g": "12px" }}>
          <Route size={22} style={{ flex: "none", marginTop: 2 }} />
          <div className="stack" style={{ "--g": "2px" }}><b>Fits your round</b><span className="small">{o.route}</span></div>
        </div>
      )}
      <dl className="facts">{o.facts.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>
      {o.note && <div className="soft small"><b>From {cust}:</b> "{o.note}"</div>}
      <div className="row" style={{ "--g": "12px" }}>
        <Avatar initials={o.customer.initials} size={42} />
        <div className="stack" style={{ "--g": "0px" }}><b>{o.customer.name}</b><span className="xs muted">{o.customer.meta}</span></div>
      </div>
      <div className="card">
        <div className="row between" style={{ alignItems: "flex-end" }}>
          <div className="stack" style={{ "--g": "4px" }}><span className="small muted">Guide price</span><span className="big-num">{fmt(o.guide)}</span></div>
          <div className="stack" style={{ "--g": "4px", textAlign: "right" }}><span className="small muted">You get</span><span className="big-num" style={{ color: "var(--primary)" }}>{fmt(provider)}</span></div>
        </div>
        <p className="xs muted" style={{ marginTop: 10 }}>After the {pct(TAKE_RATE)} {BRAND} fee. Paid to your bank with Friday's payout.</p>
      </div>

      {accepted[o.id] ? (
        <div className="card stack" style={{ "--g": "14px" }}>
          <div className="row" style={{ "--g": "12px" }}>
            <span className="success-mark sm"><Check size={22} strokeWidth={3} /></span>
            <div className="stack" style={{ "--g": "2px" }}><h2 className="h3">It's yours</h2><span className="small muted">Added to Tuesday 29 September at 10:30, straight after Widmer End.</span></div>
          </div>
          <button type="button" className="btn btn-primary btn-lg btn-block" onClick={() => go("onjob")}>See Tuesday's round</button>
        </div>
      ) : sent ? (
        <div className="card flat stack" style={{ "--g": "8px" }}>
          <div className="row" style={{ "--g": "10px" }}><Clock size={20} /><b>Waiting for {cust} to decide on {fmt(sent)}</b></div>
          <p className="small muted">We'll text you the answer. If someone accepts the guide price first, the job goes to them.</p>
        </div>
      ) : (
        <>
          {remaining != null && provider > remaining && (
            <div className="soft small row top" style={{ "--g": "10px", background: "var(--warn-soft)" }}>
              <PiggyBank size={18} style={{ flex: "none", marginTop: 2 }} />
              <span>Taking this would put you {fmt(provider - remaining)} over your {limit.period === "week" ? "weekly" : "monthly"} limit. It's your choice.</span>
            </div>
          )}
          <button type="button" className="btn btn-cta btn-lg btn-block" onClick={() => setAccepted((a) => ({ ...a, [o.id]: true }))}>Accept at {fmt(o.guide)}</button>
          <button type="button" className="btn btn-ghost btn-lg btn-block" aria-expanded={open} onClick={() => setOpen((v) => !v)}>{open ? "Cancel" : "Suggest a different price"}</button>
          {open && (
            <div className="card flat stack" style={{ "--g": "14px" }}>
              <span className="label">Your price</span>
              <div className="row wrap between" style={{ "--g": "12px" }}>
                <Stepper value={price} onChange={setPrice} min={Math.round(o.guide * 0.8)} max={o.guide * 3} step={1} format={fmt} label="Your price" />
                <div className="stack" style={{ "--g": "0px", textAlign: "right" }}><span className="xs muted">You'd get</span><b>{fmt(split(price).provider)}</b></div>
              </div>
              <span className="label">Why? <span className="muted" style={{ fontWeight: 400 }}>It helps {cust} say yes.</span></span>
              <div className="chips">{REASONS.map((r) => <Chip key={r} on={reasons.includes(r)} onClick={() => toggle(r)}>{r}</Chip>)}</div>
              <button type="button" className="btn btn-primary btn-lg btn-block" onClick={() => setCountered((c) => ({ ...c, [o.id]: price }))}>Send {fmt(price)} to {cust}</button>
              <p className="xs muted">{cust} approves it before anything is booked. If someone accepts the guide price first, the job goes to them.</p>
            </div>
          )}
          <p className="xs muted center">The first person to accept the guide price gets the job.</p>
        </>
      )}
    </>
  );
}

function PhotoCheck({ label, hint, done, onClick }) {
  return (
    <button type="button" className="toggle-row" onClick={onClick} aria-pressed={done}>
      <span className={"box" + (done ? " on" : "")}>{done && <Check size={15} strokeWidth={3} />}</span>
      <span className="grow stack" style={{ "--g": "0px" }}>
        <span style={{ fontWeight: 600 }}>{label}</span>
        {hint && <span className="xs muted">{hint}</span>}
      </span>
      <Camera size={20} />
    </button>
  );
}

function TodayScreen({ started, elapsed, startTimer, finishTimer, addTime, photos, setPhotos, go }) {
  const notify = useToast();
  const est = 38;
  const mins = elapsed / 60000;
  const over = mins > est * 1.1;
  return (
    <>
      <div className="stack" style={{ "--g": "2px" }}>
        <span className="small muted">Tuesday 29 September</span>
        <h1 className="h1">Today's round</h1>
      </div>
      <div>
        <div className="round-item done">
          <span className="round-time">9:00</span>
          <div className="stack" style={{ "--g": "0px", paddingTop: 4 }}><b>Widmer End</b><span className="small muted">Lawn mowing, done in 31 minutes</span></div>
        </div>
        <div className="round-item now">
          <span className="round-time">10:30</span>
          <div className="grow card stack" style={{ "--g": "14px", padding: 16 }}>
            <div className="stack" style={{ "--g": "2px" }}>
              <b>12 Orchard Way, Hazlemere</b>
              <span className="small muted">Lawn mowing for Sarah W., 0.4 miles from your last job</span>
            </div>
            <div className="soft small">Side gate, clippings taken away. "The side gate sticks, so please close it behind you. The dog's out."</div>
            <div className="grid2">
              <button type="button" className="btn btn-ghost" onClick={() => notify("Opens your maps app with the address")}><Navigation size={17} /> Directions</button>
              <button type="button" className="btn btn-ghost" onClick={() => notify("Opens your messages with Sarah")}><MessageCircle size={17} /> Message</button>
            </div>
            {!started ? (
              <button type="button" className="btn btn-cta btn-lg btn-block" onClick={startTimer}><Timer size={20} /> I've arrived, start the job</button>
            ) : (
              <div className="stack" style={{ "--g": "10px" }}>
                <div className="timer">{mmss(elapsed)}</div>
                <div className="progress"><i style={{ width: `${Math.min(100, (mins / est) * 100)}%`, background: over ? "var(--accent)" : undefined }} /></div>
                <div className="row between xs muted">
                  <span>{over ? "Running over the estimate, that's fine" : `Estimate ${est} minutes`}</span>
                  <button type="button" className="btn btn-link xs" onClick={addTime}>Demo: add 10 min</button>
                </div>
              </div>
            )}
            <div className="stack" style={{ "--g": "0px" }}>
              <PhotoCheck label="Before photo" done={photos.before} onClick={() => setPhotos((p) => ({ ...p, before: !p.before }))} />
              <PhotoCheck label="After photo" hint="Sent to Sarah. It also protects you if there's a disagreement." done={photos.after} onClick={() => setPhotos((p) => ({ ...p, after: !p.after }))} />
            </div>
            {started && <button type="button" className="btn btn-primary btn-lg btn-block" onClick={finishTimer}>Finish job</button>}
          </div>
        </div>
        <div className="round-item">
          <span className="round-time">13:30</span>
          <div className="stack" style={{ "--g": "0px", paddingTop: 4 }}><b>Hazlemere</b><span className="small muted">Lawn mowing, about 30 minutes</span></div>
        </div>
      </div>
      <div className="card flat stack" style={{ "--g": "10px" }}>
        <b>Can't make one of today's jobs?</b>
        <div className="grid2">
          <button type="button" className="btn btn-ghost" onClick={() => notify("Sarah's been told Tom, your helper, is coming instead")}><UserPlus size={17} /> Send Tom</button>
          <button type="button" className="btn btn-ghost" onClick={() => go("cover")}><Users size={17} /> Get cover</button>
        </div>
      </div>
    </>
  );
}

function FinishScreen({ elapsed, go, resetJob }) {
  const fromTimer = elapsed >= 60000;
  const est = 38;
  const [mins, setMins] = useState(fromTimer ? Math.round(elapsed / 60000) : est);
  const [flags, setFlags] = useState([]);
  const [done, setDone] = useState(false);
  const NONE = "Nothing, it was as described";
  const FLAGS = ["Grass was longer than described", "Access was harder", "More waste than expected", "Weather slowed me down", NONE];
  const toggle = (f) => setFlags((x) => {
    if (f === NONE) return x.includes(NONE) ? [] : [NONE];
    const y = x.filter((v) => v !== NONE);
    return y.includes(f) ? y.filter((v) => v !== f) : [...y, f];
  });
  const diff = mins - est;

  if (done) {
    return (
      <div className="stack center" style={{ "--g": "14px", alignItems: "center", paddingTop: 36 }}>
        <span className="success-mark"><Check size={32} strokeWidth={3} /></span>
        <h1 className="h1">{fmt(split(30).provider)} is on its way</h1>
        <p className="muted">It'll reach your bank with Friday's payout. Sarah has been sent your after photo.</p>
        <button type="button" className="btn btn-primary btn-lg btn-block" onClick={() => { resetJob(); go("jobs"); }}>Back to jobs</button>
      </div>
    );
  }
  return (
    <>
      <h1 className="h1">Nice work. How did it go?</h1>
      <div className="card stack" style={{ "--g": "12px" }}>
        <span className="label">How long did it take?</span>
        <Stepper value={mins} onChange={setMins} min={5} max={480} step={5} label="Minutes taken" format={(v) => `${v} min`} />
        <span className="small muted">
          {fromTimer ? "From your timer. " : ""}The estimate was {est} minutes{diff === 0 ? ", spot on." : `, so ${Math.abs(diff)} minutes ${diff > 0 ? "over" : "under"}.`}
        </span>
      </div>
      <div className="stack" style={{ "--g": "10px" }}>
        <span className="label">Was anything different from the description?</span>
        <div className="chips">{FLAGS.map((f) => <Chip key={f} on={flags.includes(f)} onClick={() => toggle(f)}>{f}</Chip>)}</div>
      </div>
      <label className="field">
        <span className="label">Anything else? <span className="muted" style={{ fontWeight: 400 }}>(optional)</span></span>
        <textarea className="input" placeholder="For example: there's a second lawn behind the shed that isn't on the plan." />
      </label>
      <div className="soft small row top" style={{ "--g": "10px" }}>
        <Info size={18} style={{ flex: "none", marginTop: 2 }} />
        <span><b>Why we ask:</b> your real times are how guide prices get fixed. If jobs like this keep taking longer than we estimate, the guide price goes up.</span>
      </div>
      <button type="button" className="btn btn-cta btn-lg btn-block" onClick={() => setDone(true)}>Send and get paid</button>
    </>
  );
}

function EarningsScreen({ go, limit, remaining }) {
  return (
    <>
      <h1 className="h1">Earnings</h1>
      <div className="card stack" style={{ "--g": "10px" }}>
        <div className="row between top">
          <div className="stack" style={{ "--g": "4px" }}><span className="small muted">This week</span><span className="big-num">{fmt(WEEK_SO_FAR)}</span></div>
          <span className="badge ok">Paid Friday 25 Sep</span>
        </div>
        <BarChart data={WEEKLY} labels={WEEK_LABELS} label="Your earnings for each of the last 8 weeks" />
      </div>
      <div className="card flat" style={{ padding: "0 16px" }}>
        <LinkRow icon={Receipt} title="Tax and records" sub="Tax pack, mileage and key dates, kept for you" onClick={() => go("tax")} />
        <LinkRow icon={PiggyBank} title="Earnings limit"
          sub={limit.on ? `${fmt(remaining)} left of ${fmt(limit.amount)} this ${limit.period}` : "Off. Useful if you get means-tested benefits."} onClick={() => go("limit")} />
        <LinkRow icon={HeartHandshake} title="Your own customers" sub="Paid through us for a much smaller fee" onClick={() => go("mycustomers")} />
      </div>
      <h2 className="h3">Payouts</h2>
      <div className="card flat" style={{ padding: "4px 16px" }}>
        {PAYOUTS.map(([d, v]) => (
          <div key={d} className="list-row">
            <span className="cat-ico sm"><Wallet size={17} /></span>
            <div className="grow stack" style={{ "--g": "0px" }}><b>{d}</b><span className="xs muted">To your bank ending 21</span></div>
            <b>{fmt(v)}</b>
          </div>
        ))}
      </div>
      <div className="card flat stack" style={{ "--g": "8px" }}>
        <div className="row" style={{ "--g": "10px" }}><FileText size={20} /><b>We tell HMRC what you earn</b></div>
        <p className="small muted">The law requires platforms like {BRAND} to report what sellers earn to HMRC. That's why we asked for your National Insurance number, and why we keep your records tidy for you.</p>
      </div>
    </>
  );
}

function MeScreen({ go, limit }) {
  const notify = useToast();
  const dave = providerById("dave");
  const [skills, setSkills] = useState(() => Object.fromEntries(CATEGORIES.map((c) => [c.id, dave.skills.includes(c.id)])));
  const [radius, setRadius] = useState(4);
  const [days, setDays] = useState({ Mon: true, Tue: true, Wed: false, Thu: true, Fri: true, Sat: true, Sun: false });
  const [alerts, setAlerts] = useState({ sms: true, whatsapp: false, quiet: true });
  const docNotes = {
    insurance: "Verified until 14 Mar 2027. We'll remind you a month before.",
    waste_carrier: "Lets you take clippings and cuttings away",
    ladder_cover: "Lets you take gutter jobs",
  };
  const missing = [...new Set(CATEGORIES.filter((c) => skills[c.id]).flatMap((c) => c.requires).filter((d) => !dave.docs.includes(d)))];
  const docs = [
    ["Identity", "Checked with Stripe", BadgeCheck],
    ...dave.docs.map((d) => [DOCS[d], docNotes[d], ShieldCheck]),
    ["Tax details for HMRC", "National Insurance number and date of birth", FileText],
    ["Bank account", "Paid out through Stripe every Friday", Wallet],
  ];
  return (
    <>
      <div className="row" style={{ "--g": "14px" }}>
        <Avatar initials="DH" size={64} />
        <div className="stack" style={{ "--g": "4px" }}>
          <h1 className="h2">Dave Hughes</h1>
          <span className="row small muted" style={{ "--g": "6px" }}><Stars value={4.9} size={14} /> 4.9 from 38 jobs</span>
          <span className="xs muted">Hazlemere, with {BRAND} since April</span>
        </div>
      </div>
      <div className="card flat" style={{ padding: "0 16px" }}>
        <LinkRow icon={Plane} title="Time off and helpers" sub="Cover for your regulars, and Tom as your helper" onClick={() => go("cover")} />
        <LinkRow icon={PiggyBank} title="Earnings limit" sub={limit.on ? `${fmt(limit.amount)} a ${limit.period}` : "Off"} onClick={() => go("limit")} />
        <LinkRow icon={Receipt} title="Tax and records" sub="Your tax pack builds itself as you work" onClick={() => go("tax")} />
        <LinkRow icon={HeartHandshake} title="Your own customers" sub={`Bring them on for a ${pct(BYOC_RATE)} fee instead of ${pct(TAKE_RATE)}`} onClick={() => go("mycustomers")} />
      </div>
      <div className="card flat" style={{ padding: "4px 16px" }}>
        {docs.map(([t, d, I]) => (
          <div key={t} className="doc-row">
            <span className="cat-ico sm"><I size={17} /></span>
            <div className="grow stack" style={{ "--g": "0px" }}><b>{t}</b>{d && <span className="xs muted">{d}</span>}</div>
            <span className="badge ok"><Check size={12} /> Done</span>
          </div>
        ))}
      </div>
      <div className="stack" style={{ "--g": "12px" }}>
        <h2 className="h3">Jobs I do</h2>
        {GROUPS.map((g) => (
          <div key={g.id} className="stack" style={{ "--g": "8px" }}>
            <span className="small muted">{g.name}</span>
            <div className="chips">
              {CATEGORIES.filter((c) => c.group === g.id && c.status === "live").map((c) => (
                <Chip key={c.id} on={skills[c.id]} onClick={() => setSkills((s) => ({ ...s, [c.id]: !s[c.id] }))}><CatIcon id={c.id} size={16} /> {c.name}</Chip>
              ))}
            </div>
          </div>
        ))}
        {missing.length > 0 && (
          <div className="soft small stack" style={{ "--g": "6px" }}>
            <span>To take all of these, we'll also need: <b>{missing.map((d) => DOCS[d]).join(", ")}</b>.</span>
            <button type="button" className="btn btn-link small" style={{ alignSelf: "flex-start" }} onClick={() => notify("We'll walk you through it. A basic DBS check takes a few days.")}>Sort it now</button>
          </div>
        )}
      </div>
      <div className="stack" style={{ "--g": "10px" }}>
        <h2 className="h3">How far I'll travel</h2>
        <div className="row wrap" style={{ "--g": "12px" }}>
          <Stepper value={radius} onChange={setRadius} min={1} max={15} label="Travel distance" format={(v) => `${v} ${v === 1 ? "mile" : "miles"}`} />
          <span className="small muted">from HP15</span>
        </div>
      </div>
      <div className="stack" style={{ "--g": "10px" }}>
        <h2 className="h3">Days I work</h2>
        <div className="chips">{Object.keys(days).map((d) => <Chip key={d} on={days[d]} onClick={() => setDays((x) => ({ ...x, [d]: !x[d] }))}>{d}</Chip>)}</div>
      </div>
      <div className="card flat" style={{ padding: "0 16px" }}>
        <Toggle on={alerts.sms} onChange={(v) => setAlerts((a) => ({ ...a, sms: v }))} label="New jobs by text" />
        <hr />
        <Toggle on={alerts.whatsapp} onChange={(v) => setAlerts((a) => ({ ...a, whatsapp: v }))} label="New jobs on WhatsApp" />
        <hr />
        <Toggle on={alerts.quiet} onChange={(v) => setAlerts((a) => ({ ...a, quiet: v }))} label="Quiet hours" hint="No alerts between 8pm and 8am" />
      </div>
      <div className="soft stack" style={{ "--g": "6px" }}>
        <b>Put {BRAND} on your home screen</b>
        <span className="small">In your browser's menu, tap "Add to Home Screen". It then opens like an app, with nothing to download.</span>
        <button type="button" className="btn btn-link small" style={{ alignSelf: "flex-start" }} onClick={() => notify("Shows step-by-step pictures for your phone")}>Show me how</button>
      </div>
    </>
  );
}

function OnboardingScreen({ go }) {
  const notify = useToast();
  const [ni, setNi] = useState("");
  const [dob, setDob] = useState("");
  const [taxDone, setTaxDone] = useState(false);
  const steps = [
    ["Your details", "Name, address and phone", "done"],
    ["Check your ID", "Done with Stripe using a passport or driving licence", "done"],
    ["Tax details", "", taxDone ? "done" : "now"],
    ["Insurance", "Upload your public liability certificate", taxDone ? "now" : "todo"],
    ["What you do and where", "Jobs, travel distance and days", "todo"],
    ["Get paid", "Connect your bank through Stripe", "todo"],
  ];
  const doneCount = steps.filter((s) => s[2] === "done").length;
  return (
    <>
      <div className="stack" style={{ "--g": "6px" }}>
        <h1 className="h1">Let's get you set up</h1>
        <p className="muted">About 10 minutes. You can stop and come back any time.</p>
      </div>
      <div className="stack" style={{ "--g": "6px" }}>
        <span className="small muted">{doneCount} of {steps.length} done</span>
        <div className="progress"><i style={{ width: `${(doneCount / steps.length) * 100}%` }} /></div>
      </div>
      <div className="card flat stack" style={{ "--g": "8px", background: "var(--warn-soft)", borderColor: "transparent" }}>
        <div className="row" style={{ "--g": "10px" }}><AlertTriangle size={20} /><b>Before you start</b></div>
        <p className="small">If you get Pension Credit, Universal Credit or other means-tested support, earnings from jobs can affect it. You can set a limit, and we'll stop offering you jobs once you reach it.</p>
        <div className="row wrap" style={{ "--g": "16px" }}>
          <button type="button" className="btn btn-primary btn-sm" onClick={() => go("limit")}><PiggyBank size={15} /> Set an earnings limit</button>
          <button type="button" className="btn btn-link small" onClick={() => notify("Opens the benefits guide")}>Read the guide</button>
        </div>
      </div>
      <div className="stack" style={{ "--g": "10px" }}>
        {steps.map(([t, d, s], i) => (
          <div key={t} className={s === "now" ? "card stack" : "card flat stack"} style={{ "--g": "12px", padding: 16, opacity: s === "todo" ? 0.6 : 1 }}>
            <div className="row" style={{ "--g": "12px" }}>
              <span className={"box" + (s === "done" ? " on" : "")} style={{ borderRadius: 99, width: 28, height: 28 }}>
                {s === "done" ? <Check size={15} strokeWidth={3} /> : <span className="xs" style={{ fontWeight: 700 }}>{i + 1}</span>}
              </span>
              <div className="grow stack" style={{ "--g": "0px" }}>
                <b>{t}</b>
                {d && <span className="xs muted">{d}</span>}
              </div>
            </div>
            {s === "now" && t === "Tax details" && (
              <div className="stack" style={{ "--g": "12px" }}>
                <p className="small muted">The law requires us to collect these because we report earnings to HMRC. We don't use them for anything else.</p>
                <label className="field"><span className="label">National Insurance number</span><input className="input" value={ni} onChange={(e) => setNi(e.target.value.toUpperCase())} placeholder="QQ 12 34 56 C" /></label>
                <label className="field"><span className="label">Date of birth</span><input className="input" value={dob} onChange={(e) => setDob(e.target.value)} placeholder="DD / MM / YYYY" inputMode="numeric" /></label>
                <button type="button" className="btn btn-primary btn-lg btn-block" disabled={!ni.trim() || !dob.trim()} onClick={() => setTaxDone(true)}>Save tax details</button>
              </div>
            )}
            {s === "now" && t === "Insurance" && (
              <div className="stack" style={{ "--g": "12px" }}>
                <button type="button" className="btn btn-primary btn-lg btn-block" onClick={() => notify("Opens your camera or files")}><Camera size={18} /> Photograph your certificate</button>
                <button type="button" className="btn btn-link small" style={{ alignSelf: "flex-start" }} onClick={() => notify("Opens our guide to getting cover")}>Don't have cover yet? Read our guide</button>
              </div>
            )}
          </div>
        ))}
      </div>
      <div className="card flat row" style={{ "--g": "12px" }}>
        <Phone size={20} style={{ flex: "none" }} />
        <div className="grow small">Stuck on anything? Our local team will ring you back.</div>
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => notify("Call-back requested")}>Call me</button>
      </div>
      <button type="button" className="btn btn-link" style={{ alignSelf: "center" }} onClick={() => go("jobs")}>Prototype: skip to a set-up account</button>
    </>
  );
}

const WEEK_SO_FAR = 212.5; // what Dave has received this week (mock)

const MONTH_SO_FAR = 834.5; // and this calendar month

function LimitStrip({ limit, remaining, earned, onClick }) {
  const used = Math.min(100, (earned / limit.amount) * 100);
  return (
    <button type="button" className="card flat stack limit-strip" style={{ "--g": "8px" }} onClick={onClick}>
      <span className="row" style={{ "--g": "10px" }}>
        <PiggyBank size={20} />
        <span className="grow small"><b>{fmt(remaining)} left</b> of your {fmt(limit.amount)} {limit.period === "week" ? "weekly" : "monthly"} limit</span>
        <ChevronRight size={18} />
      </span>
      <span className="progress" aria-hidden="true"><i style={{ width: `${used}%`, background: used >= 100 ? "var(--accent)" : undefined }} /></span>
    </button>
  );
}

function LinkRow({ icon: I, title, sub, onClick }) {
  return (
    <button type="button" className="link-row" onClick={onClick}>
      <span className="cat-ico sm"><I size={17} /></span>
      <span className="grow stack" style={{ "--g": "0px" }}><b>{title}</b>{sub && <span className="xs muted">{sub}</span>}</span>
      <ChevronRight size={18} />
    </button>
  );
}

function TaxScreen({ go }) {
  const notify = useToast();
  const received = 2864;
  const turnover = Math.round((received / (1 - TAKE_RATE)) * 100) / 100;
  const fees = Math.round((turnover - received) * 100) / 100;
  const miles = 612;
  const mileage = Math.round(miles * 45) / 100;
  const kit = [["Mower service", 65], ["Strimmer line", 18], ["Petrol for tools", 59]];
  const kitTotal = kit.reduce((s, [, v]) => s + v, 0);
  const costs = Math.round((fees + mileage + kitTotal) * 100) / 100;
  const allowanceProfit = Math.round((turnover - 1000) * 100) / 100;
  const costsProfit = Math.round((turnover - costs) * 100) / 100;
  const allowanceWins = allowanceProfit <= costsProfit;
  const trips = [["Tue 22 Sep", "Home, Widmer End, Hazlemere, home", 5.8], ["Thu 17 Sep", "Home, Widmer End, home", 3.9], ["Tue 15 Sep", "Home, Hazlemere, Holmer Green, home", 6.4]];
  return (
    <>
      <button type="button" className="btn btn-link" style={{ alignSelf: "flex-start" }} onClick={() => go("earnings")}><ArrowLeft size={18} /> Earnings</button>
      <div className="stack" style={{ "--g": "6px" }}>
        <h1 className="h1">Tax and records</h1>
        <p className="muted">Kept for you as you work. This tax year started on 6 April 2026.</p>
      </div>

      <div className="card stack" style={{ "--g": "10px" }}>
        <div className="row between"><span>Customers paid you</span><b>{fmt(turnover)}</b></div>
        <div className="row between"><span>{BRAND} fees</span><b>−{fmt(fees)}</b></div>
        <hr />
        <div className="row between"><span>Reached your bank</span><b>{fmt(received)}</b></div>
        <p className="xs muted">For tax, your turnover is what customers paid, not what reached your bank. Our fee counts as a business cost.</p>
      </div>

      <div className="card stack" style={{ "--g": "12px" }}>
        <h2 className="h3">Allowance or costs?</h2>
        <p className="small muted">You can take the £1,000 trading allowance or claim your actual costs, but not both. We compare them for you.</p>
        <div className={"cmp" + (allowanceWins ? " win" : "")}>
          <div className="stack" style={{ "--g": "0px" }}><b>Trading allowance</b><span className="xs muted">£1,000 off your turnover</span></div>
          <div className="stack" style={{ "--g": "0px", textAlign: "right" }}><span className="xs muted">Taxable profit</span><b>{fmt(allowanceProfit)}</b></div>
        </div>
        <div className={"cmp" + (!allowanceWins ? " win" : "")}>
          <div className="stack" style={{ "--g": "0px" }}><b>Actual costs</b><span className="xs muted">Fees, mileage and kit: {fmt(costs)}</span></div>
          <div className="stack" style={{ "--g": "0px", textAlign: "right" }}><span className="xs muted">Taxable profit</span><b>{fmt(costsProfit)}</b></div>
        </div>
        <div className="soft small">
          <b>{allowanceWins ? "The allowance" : "Claiming your costs"} works out better so far,</b> by {fmt(Math.abs(allowanceProfit - costsProfit))} of profit. Your costs grow as you work, so we check again every month and tell you if it flips.
        </div>
      </div>

      <div className="card stack" style={{ "--g": "10px" }}>
        <div className="row between"><h2 className="h3">Mileage</h2><span className="badge ok"><Car size={13} /> Logged for you</span></div>
        <div className="row between wrap" style={{ alignItems: "baseline" }}>
          <span className="big-num">{miles} miles</span>
          <span className="small muted">worth {fmt(mileage)} at 45p a mile</span>
        </div>
        <div>
          {trips.map(([d, r, m]) => (
            <div key={d} className="list-row">
              <div className="grow stack" style={{ "--g": "0px" }}><b className="small">{d}</b><span className="xs muted">{r}</span></div>
              <span className="small">{m} mi</span>
            </div>
          ))}
        </div>
        <p className="xs muted">Worked out from your jobs, starting and ending at home. It only counts if you claim actual costs.</p>
      </div>

      <div className="card flat stack" style={{ "--g": "8px" }}>
        <div className="row between"><h2 className="h3">Kit and supplies</h2><b>{fmt(kitTotal)}</b></div>
        {kit.map(([n, v]) => <div key={n} className="row between small"><span>{n}</span><span>{fmt(v)}</span></div>)}
        <button type="button" className="btn btn-ghost btn-block" style={{ marginTop: 6 }} onClick={() => notify("Opens your camera. We read the receipt for you.")}><Camera size={17} /> Snap a receipt</button>
      </div>

      <div className="card flat stack" style={{ "--g": "10px" }}>
        <h2 className="h3">Key dates</h2>
        <div className="row top" style={{ "--g": "12px" }}><div className="date-chip"><span>Oct</span><b>5</b></div><span className="small">By 5 October 2027, register for Self Assessment if this is your first year working for yourself.</span></div>
        <div className="row top" style={{ "--g": "12px" }}><div className="date-chip"><span>Jan</span><b>31</b></div><span className="small">By 31 January 2028, send your return and pay any tax due.</span></div>
        <p className="xs muted">We'll text you a month before each date. Making Tax Digital for Income Tax is due to reach turnover over £20,000 from April 2028. You're well under.</p>
      </div>

      <button type="button" className="btn btn-cta btn-lg btn-block" onClick={() => notify("Tax pack ready to download or send to your accountant")}><Download size={18} /> Download your tax pack</button>
      <p className="xs muted">Laid out in the order of HMRC's self-employment pages. The trading allowance covers all your self-employed income, not just {BRAND}. We're not tax advisers.</p>
    </>
  );
}

function LimitScreen({ limit, setLimit, go }) {
  const notify = useToast();
  const [draft, setDraft] = useState(limit);
  const [benefit, setBenefit] = useState(null);
  const INFO = {
    state: ["Your State Pension isn't means-tested, so earning more doesn't reduce it. The money may still be taxable.", null],
    pc: ["Pension Credit is worked out weekly. Earnings above a small amount (often £5 a week for a single person) reduce it pound for pound. Speak to the Pension Service or Citizens Advice before choosing a limit.", "week"],
    uc: ["Universal Credit goes down by 55p for every £1 you earn, after any work allowance you have. It's assessed monthly, so a monthly limit fits best.", "month"],
    none: ["You may not need a limit, but some people like one to keep jobs to pocket money.", null],
  };
  const pick = (k) => { setBenefit(k); const period = INFO[k][1]; if (period) setDraft((d) => ({ ...d, period })); };
  const earned = draft.period === "week" ? WEEK_SO_FAR : MONTH_SO_FAR;
  const left = Math.max(0, draft.amount - earned);
  const used = Math.min(100, (earned / draft.amount) * 100);
  const setAmount = (v) => setDraft((d) => ({ ...d, amount: v }));
  return (
    <>
      <button type="button" className="btn btn-link" style={{ alignSelf: "flex-start" }} onClick={() => go("earnings")}><ArrowLeft size={18} /> Earnings</button>
      <div className="stack" style={{ "--g": "6px" }}>
        <h1 className="h1">Earnings limit</h1>
        <p className="muted">Choose a limit and we'll stop offering you new jobs once you reach it. Jobs you've already accepted always go ahead.</p>
      </div>
      <div className="card flat" style={{ padding: "0 16px" }}>
        <Toggle on={draft.on} onChange={(v) => setDraft((d) => ({ ...d, on: v }))} label="Use an earnings limit" />
      </div>
      {draft.on && (
        <>
          <div className="stack" style={{ "--g": "10px" }}>
            <span className="label">Do you get any of these?</span>
            <span className="hint">Only so we can suggest a sensible limit. We don't save your answer, just the limit.</span>
            <div className="chips">
              {[["state", "State Pension"], ["pc", "Pension Credit"], ["uc", "Universal Credit"], ["none", "None of these"]].map(([k, l]) => (
                <Chip key={k} on={benefit === k} onClick={() => pick(k)}>{l}</Chip>
              ))}
            </div>
            {benefit && <div className="soft small">{INFO[benefit][0]}</div>}
          </div>
          <div className="stack" style={{ "--g": "10px" }}>
            <span className="label">Limit per</span>
            <div className="chips">
              <Chip on={draft.period === "week"} onClick={() => setDraft((d) => ({ ...d, period: "week" }))}>Week</Chip>
              <Chip on={draft.period === "month"} onClick={() => setDraft((d) => ({ ...d, period: "month" }))}>Month</Chip>
            </div>
          </div>
          <div className="stack" style={{ "--g": "10px" }}>
            <span className="label">Your limit</span>
            <Stepper value={draft.amount} onChange={setAmount} min={5} max={5000} step={draft.amount < 100 ? 5 : 25} format={fmt} label="Your limit" />
            <span className="hint">Counts what you receive after our fee.</span>
          </div>
          <div className="card stack" style={{ "--g": "10px" }}>
            <div className="row between"><span className="small">This {draft.period} so far</span><b>{fmt(earned)} of {fmt(draft.amount)}</b></div>
            <div className="progress" aria-hidden="true"><i style={{ width: `${used}%`, background: used >= 100 ? "var(--accent)" : undefined }} /></div>
            <span className="small muted">
              {left > 0
                ? `${fmt(left)} left. Jobs that would take you over are marked, so you can choose.`
                : `You've reached it. New job alerts are paused until ${draft.period === "week" ? "Monday" : "the 1st"}.`}
            </span>
          </div>
          <p className="xs muted">This helps you stay within a number you've chosen. It isn't benefits advice. For that, try Citizens Advice or the Turn2us benefits calculator.</p>
        </>
      )}
      <button type="button" className="btn btn-primary btn-lg btn-block"
        onClick={() => { setLimit(draft); notify(draft.on ? `Limit saved: ${fmt(draft.amount)} a ${draft.period}` : "Earnings limit turned off"); go("jobs"); }}>Save</button>
    </>
  );
}

function CoverScreen({ go }) {
  const notify = useToast();
  const [from, setFrom] = useState("Mon 12 Oct");
  const [to, setTo] = useState("Sun 18 Oct");
  const regulars = [
    { id: "sw", name: "Sarah W.", job: "Lawn mowing, Tue 13 Oct", where: "Hazlemere" },
    { id: "mt", name: "Margaret T.", job: "Lawn mowing, Tue 13 Oct", where: "Widmer End" },
    { id: "rb", name: "Robert B.", job: "Hedge trimming, Thu 15 Oct", where: "Widmer End" },
  ];
  const [plan, setPlan] = useState({ sw: "cover", mt: "helper", rb: "skip" });
  const opts = [["cover", "Local cover"], ["helper", "Send Tom"], ["skip", "Skip it"]];
  return (
    <>
      <button type="button" className="btn btn-link" style={{ alignSelf: "flex-start" }} onClick={() => go("me")}><ArrowLeft size={18} /> Me</button>
      <h1 className="h1">Time off and helpers</h1>

      <div className="card stack" style={{ "--g": "14px" }}>
        <div className="row" style={{ "--g": "10px" }}><Plane size={20} /><h2 className="h3">Time off</h2></div>
        <div className="grid2">
          <label className="field"><span className="label">Away from</span><input className="input" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
          <label className="field"><span className="label">Back on</span><input className="input" value={to} onChange={(e) => setTo(e.target.value)} /></label>
        </div>
        <span className="label">Your visits while you're away</span>
        {regulars.map((r) => (
          <div key={r.id} className="stack" style={{ "--g": "8px", paddingBottom: 6 }}>
            <div className="stack" style={{ "--g": "0px" }}><b>{r.name}</b><span className="xs muted">{r.job}, {r.where}</span></div>
            <div className="chips">{opts.map(([v, l]) => <Chip key={v} on={plan[r.id] === v} onClick={() => setPlan((p) => ({ ...p, [r.id]: v }))}>{l}</Chip>)}</div>
          </div>
        ))}
        <div className="soft small stack" style={{ "--g": "4px" }}>
          <b>Your customers stay yours.</b>
          <span>Whoever covers gets the visit, not the customer. Your regulars come straight back to you afterwards, and covers can't take them on privately.</span>
        </div>
        <button type="button" className="btn btn-primary btn-lg btn-block" onClick={() => notify("Arranged. Your customers have been told who's coming.")}>Arrange cover</button>
      </div>

      <div className="card stack" style={{ "--g": "14px" }}>
        <div className="row" style={{ "--g": "10px" }}><UserPlus size={20} /><h2 className="h3">Your helpers</h2></div>
        <p className="small muted">You can send a helper in your place. They do the job, you get paid, and you pay them however you've agreed. The customer is always told who's coming.</p>
        <div className="row top" style={{ "--g": "12px" }}>
          <Avatar initials="TH" size={48} />
          <div className="grow stack" style={{ "--g": "6px" }}>
            <div className="stack" style={{ "--g": "0px" }}><b>Tom Hughes</b><span className="xs muted">Your son. Ready to send.</span></div>
            <div className="row wrap" style={{ "--g": "6px" }}>
              <span className="badge ok"><BadgeCheck size={12} /> ID checked</span>
              <span className="badge ok"><ShieldCheck size={12} /> Basic DBS</span>
              <span className="badge ok"><ShieldCheck size={12} /> Insured to Jun 2027</span>
            </div>
          </div>
        </div>
        <button type="button" className="btn btn-ghost btn-block" onClick={() => notify("We've texted them a sign-up link. It takes about 10 minutes.")}><Plus size={17} /> Add a helper</button>
        <p className="xs muted">Helpers go through the same ID, DBS and insurance checks as you before they can do a job.</p>
      </div>
    </>
  );
}

function OwnCustomersScreen({ go }) {
  const notify = useToast();
  const dave = providerById("dave");
  const [list, setList] = useState(OWN_CUSTOMERS);
  const blank = { name: "", phone: "", cat: dave.skills[0], price: 30, freq: "fortnightly" };
  const [form, setForm] = useState(blank);
  const [blocked, setBlocked] = useState(false);
  const std = split(30);
  const own = splitOwn(30);
  const freqs = [["fortnightly", "Every 2 weeks"], ["monthly", "Monthly"], ["oneoff", "Just once"]];
  const set = (k, v) => { setBlocked(false); setForm((f) => ({ ...f, [k]: v })); };
  const digits = form.phone.replace(/\D/g, "");
  const valid = form.name.trim() && digits.length >= 10;
  const send = () => {
    if (PLATFORM_PHONES.includes(digits)) { setBlocked(true); return; }
    const freq = freqs.find(([v]) => v === form.freq)[1];
    setList((l) => [...l, { id: digits, name: form.name.trim(), where: "", cat: form.cat, price: form.price, freq, status: "invited" }]);
    notify(`Invite sent to ${firstName(form.name)} by text`);
    setForm(blank);
  };
  return (
    <>
      <button type="button" className="btn btn-link" style={{ alignSelf: "flex-start" }} onClick={() => go("me")}><ArrowLeft size={18} /> Me</button>
      <div className="stack" style={{ "--g": "6px" }}>
        <h1 className="h1">Your own customers</h1>
        <p className="muted">Bring the customers you already have. We handle reminders, card payments, receipts and your tax records, for a much smaller fee.</p>
      </div>

      <div className="card stack" style={{ "--g": "12px" }}>
        <span className="small muted">On a {fmt(30)} job, you keep</span>
        <div className="grid2">
          <div className="cmp win" style={{ flexDirection: "column", alignItems: "flex-start", gap: 2 }}>
            <span className="xs muted">Your own customer</span>
            <span className="big-num" style={{ fontSize: 28 }}>{fmt(own.provider)}</span>
            <span className="xs muted">{pct(BYOC_RATE)} fee, {fmt(BYOC_MIN)} minimum</span>
          </div>
          <div className="cmp" style={{ flexDirection: "column", alignItems: "flex-start", gap: 2 }}>
            <span className="xs muted">A customer we found</span>
            <span className="big-num" style={{ fontSize: 28 }}>{fmt(std.provider)}</span>
            <span className="xs muted">{pct(TAKE_RATE)} fee</span>
          </div>
        </div>
      </div>

      <div className="card flat" style={{ padding: "4px 16px" }}>
        {list.map((c) => (
          <div key={c.id} className="list-row">
            <Avatar initials={initialsOf(c.name)} size={40} />
            <div className="grow stack" style={{ "--g": "0px" }}>
              <b>{c.name}</b>
              <span className="xs muted">{catById(c.cat).name}, {c.freq.toLowerCase()}, {fmt(c.price)}</span>
            </div>
            {c.status === "active" ? <span className="badge ok">Active</span> : <span className="badge warn">Invite sent</span>}
          </div>
        ))}
      </div>

      <div className="card stack" style={{ "--g": "14px" }}>
        <h2 className="h3">Invite a customer</h2>
        <label className="field"><span className="label">Their name</span><input className="input" value={form.name} onChange={(e) => set("name", e.target.value)} /></label>
        <label className="field"><span className="label">Their mobile</span><input className="input" value={form.phone} inputMode="tel" onChange={(e) => set("phone", e.target.value)} /></label>
        <span className="xs muted">Prototype: try 07700 900123 to see what happens with someone who's already a {BRAND} customer.</span>
        <div className="stack" style={{ "--g": "8px" }}>
          <span className="label">The job</span>
          <div className="chips">{dave.skills.map((id) => <Chip key={id} on={form.cat === id} onClick={() => set("cat", id)}><CatIcon id={id} size={16} /> {catById(id).name}</Chip>)}</div>
        </div>
        <div className="stack" style={{ "--g": "8px" }}>
          <span className="label">Your price</span>
          <div className="row wrap between" style={{ "--g": "12px" }}>
            <Stepper value={form.price} onChange={(v) => set("price", v)} min={5} max={500} step={1} format={fmt} label="Your price" />
            <div className="stack" style={{ "--g": "0px", textAlign: "right" }}><span className="xs muted">You'd keep</span><b>{fmt(splitOwn(form.price).provider)}</b></div>
          </div>
          <span className="hint">For your own customers, the price is entirely yours. There's no guide price.</span>
        </div>
        <div className="stack" style={{ "--g": "8px" }}>
          <span className="label">How often</span>
          <div className="chips">{freqs.map(([v, l]) => <Chip key={v} on={form.freq === v} onClick={() => set("freq", v)}>{l}</Chip>)}</div>
        </div>
        {blocked && (
          <div className="soft small row top" style={{ "--g": "10px", background: "var(--warn-soft)" }}>
            <Info size={18} style={{ flex: "none", marginTop: 2 }} />
            <span>That number already belongs to a {BRAND} customer, so they stay on the standard fee. Any regular work you already do for them is still yours.</span>
          </div>
        )}
        <button type="button" className="btn btn-primary btn-lg btn-block" disabled={!valid} onClick={send}>Send invite</button>
        <p className="xs muted">They get a text from you, sent through {BRAND}, and agree to the same customer terms as everyone else.</p>
      </div>

      <div className="soft small stack" style={{ "--g": "4px" }}>
        <b>Who counts as your own customer</b>
        <span>Someone you invite who hasn't booked through {BRAND} before. Customers who found you through {BRAND} stay on the standard fee, even if they later book you directly.</span>
      </div>
    </>
  );
}

/* ============================== Admin surface ============================== */

function AdminApp({ screen, go }) {
  const items = [
    ["overview", "Overview", LayoutDashboard],
    ["providers", "Providers", Users],
    ["calibration", "Pricing", Gauge],
    ["disputes", "Disputes", Scale],
    ["categories", "Categories", Layers],
  ];
  return (
    <div className="a-shell">
      <nav className="a-side" aria-label="Admin">
        <div className="a-brand"><span className="brand sm"><span className="brand-mark"><Sprout size={14} /></span>{BRAND} ops</span></div>
        {items.map(([id, label, I]) => (
          <button key={id} type="button" className={"a-nav" + (screen === id ? " on" : "")} aria-current={screen === id ? "page" : undefined} onClick={() => go(id)}>
            <I size={18} /> {label}
          </button>
        ))}
        <div className="a-side-foot">Manual dispatch mode. Providers are sent jobs by hand until Phase 2.</div>
      </nav>
      <main className="a-main">
        {screen === "overview" && <AdminOverview go={go} />}
        {screen === "providers" && <AdminProviders />}
        {screen === "calibration" && <AdminCalibration />}
        {screen === "disputes" && <AdminDisputes />}
        {screen === "categories" && <AdminCategories />}
      </main>
    </div>
  );
}

function AdminHeader({ title, sub, right }) {
  return (
    <div className="row between wrap top" style={{ "--g": "12px" }}>
      <div className="stack" style={{ "--g": "4px" }}>
        <h1 className="h1">{title}</h1>
        {sub && <span className="muted">{sub}</span>}
      </div>
      {right}
    </div>
  );
}

function AdminOverview({ go }) {
  const notify = useToast();
  const [shown, setShown] = useState(null);
  const kpis = [
    ["Requests", "52", "6 more than last week"],
    ["Filled", "47", "90% fill rate"],
    ["Time to first yes", "41 min", "median"],
    ["Taken at guide price", "68%", "the rest countered"],
    ["Job value", fmt(1742), "all jobs this week"],
    ["Our revenue", fmt(261.3), `${pct(TAKE_RATE)} of job value`],
  ];
  const message = (r) => {
    const { provider } = split(r.guide);
    return `Job going: ${catById(r.cat).name.toLowerCase()} in ${r.where}. ${r.brief}. Guide price ${fmt(r.guide)}, you'd get ${fmt(provider)}. Take it here: ${LINK}/j/${r.id}`;
  };
  const copy = async (r) => {
    setShown(r.id);
    try {
      await navigator.clipboard.writeText(message(r));
      notify("Copied. Paste it into the providers' WhatsApp group.");
    } catch (e) {
      notify("Couldn't copy in this preview. The message is shown below the request.");
    }
  };
  const maxJobs = Math.max(...DISTRICTS.map((d) => d.jobs));
  const attention = [
    ["Alan P.", "Insurance expires on 2 October", "warn", "Send reminder"],
    ["Jan K.", "Tax details missing, so payouts are paused", "danger", "Chase"],
    ["Ken A.", "Stuck on tax details for 6 days", "warn", "Ring him"],
  ];
  return (
    <>
      <AdminHeader title="This week" sub="Monday 21 to Sunday 27 September"
        right={<span className="badge warn"><Calendar size={13} /> Late season: winter pauses start in November</span>} />
      <div className="kpis">
        {kpis.map(([l, v, s]) => (
          <div key={l} className="card flat kpi">
            <span className="small muted">{l}</span>
            <div className="v">{v}</div>
            <span className="xs muted">{s}</span>
          </div>
        ))}
      </div>
      <div className="a-cols">
        <div className="card stack" style={{ "--g": "4px" }}>
          <div className="row between" style={{ paddingBottom: 8 }}>
            <h2 className="h3">Waiting for a provider</h2>
            <span className="badge danger">{UNFILLED.length} jobs</span>
          </div>
          {UNFILLED.map((r) => (
            <div key={r.id} className="req">
              <div className="row between top" style={{ "--g": "12px" }}>
                <div className="row top" style={{ "--g": "12px" }}>
                  <span className="cat-ico sm"><CatIcon id={r.cat} size={17} /></span>
                  <div className="stack" style={{ "--g": "0px" }}>
                    <b>{catById(r.cat).name} in {r.where}</b>
                    <span className="small muted">Request {r.id}, waiting {r.age}</span>
                  </div>
                </div>
                <b>{fmt(r.guide)}</b>
              </div>
              <span className="small">{r.why}</span>
              <div className="row wrap" style={{ "--g": "8px" }}>
                <button type="button" className="btn btn-primary btn-sm" onClick={() => copy(r)}><Copy size={15} /> Copy WhatsApp message</button>
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => notify(`Guide price for ${r.id} raised to ${fmt(Math.round(r.guide * 1.1))}. Logged for review.`)}>Raise guide 10%</button>
              </div>
              {shown === r.id && <div className="soft small">{message(r)}</div>}
            </div>
          ))}
        </div>
        <div className="stack" style={{ "--g": "18px" }}>
          <div className="card stack" style={{ "--g": "12px" }}>
            <div className="stack" style={{ "--g": "2px" }}>
              <h2 className="h3">Where the work is</h2>
              <span className="small muted">Jobs filled this week by postcode district. Darker means more jobs.</span>
            </div>
            <div className="tiles">
              {DISTRICTS.map((d) => {
                const o = 0.12 + (d.jobs / maxJobs) * 0.8;
                return (
                  <div key={d.code} className={"tile" + (o > 0.5 ? " dark" : "")}>
                    <span className="fill" style={{ opacity: o }} />
                    <div className="in">
                      <b>{d.code}</b>
                      <span className="xs muted">{d.name}</span>
                      <span className="xs" style={{ fontWeight: 600 }}>{d.jobs} jobs, {d.providers} {d.providers === 1 ? "provider" : "providers"}</span>
                    </div>
                  </div>
                );
              })}
            </div>
            <p className="small">HP11 and HP9 have demand but no active providers. Recruit there before advertising further out.</p>
          </div>
          <div className="card stack" style={{ "--g": "12px" }}>
            <div className="row between"><h2 className="h3">Customers providers brought</h2><span className="badge ok">{pct(BYOC_RATE)} fee</span></div>
            <div className="grid2">
              {[["Active", "23", "from 9 providers"], ["Job value", fmt(1148), "this week"], ["Our revenue", fmt(58.2), "includes £1 minimums"], ["Invites blocked", "2", "already our customers"]].map(([l, v, sub]) => (
                <div key={l} className="stack" style={{ "--g": "0px" }}>
                  <span className="xs muted">{l}</span>
                  <span className="big-num" style={{ fontSize: 24 }}>{v}</span>
                  <span className="xs muted">{sub}</span>
                </div>
              ))}
            </div>
            <p className="small muted">The real return isn't the 5%. Watch whether providers who bring customers also take more of ours, and stay longer.</p>
          </div>
          <div className="card stack" style={{ "--g": "4px" }}>
            <h2 className="h3" style={{ paddingBottom: 6 }}>Providers needing attention</h2>
            {attention.map(([who, what, tone, action]) => (
              <div key={who} className="list-row">
                <span className={`badge ${tone}`}>{who}</span>
                <span className="grow small">{what}</span>
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => go("providers")}>{action}</button>
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  );
}

function AdminProviders() {
  const [filter, setFilter] = useState("all");
  const needs = (p) => p.insurance.status !== "ok" || p.hmrc !== "ok";
  const rows = PROVIDERS.filter((p) => filter === "all" || (filter === "attention" && needs(p)) || (filter === "signup" && p.status === "Signing up"));
  const insBadge = (p) => p.insurance.status === "ok" ? <span className="badge ok">Until {p.insurance.expires}</span>
    : p.insurance.status === "warn" ? <span className="badge warn"><AlertTriangle size={12} /> Expires {p.insurance.expires}</span>
      : <span className="badge danger">Missing</span>;
  return (
    <>
      <AdminHeader title="Providers" sub={`${PROVIDERS.filter((p) => p.status !== "Signing up").length} active, 1 signing up`} />
      <div className="chips">
        {[["all", "Everyone"], ["attention", "Needs attention"], ["signup", "Signing up"]].map(([v, l]) => <Chip key={v} on={filter === v} onClick={() => setFilter(v)}>{l}</Chip>)}
      </div>
      <div className="card">
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Provider</th><th>Area</th><th>Jobs they do</th><th>Rating</th><th>Jobs, 30 days</th><th>Accept rate</th><th>Insurance</th><th>HMRC details</th><th>Status</th></tr></thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.id}>
                  <td><div className="row" style={{ "--g": "10px" }}><Avatar initials={p.initials} size={32} /><b>{p.name}</b></div></td>
                  <td>{p.area} <span className="muted">{p.district}</span></td>
                  <td><div className="row" style={{ "--g": "4px" }}>{p.skills.map((s) => <span key={s} className="badge" title={catById(s).name}><CatIcon id={s} size={13} /> {catById(s).short}</span>)}</div></td>
                  <td>{p.rating ? <span className="row" style={{ "--g": "4px" }}><Star size={14} fill="var(--star)" color="var(--star)" /> {p.rating.toFixed(1)} <span className="muted">({p.reviews})</span></span> : <span className="muted">None yet</span>}</td>
                  <td>{p.jobs30}</td>
                  <td>{p.accept == null ? <span className="muted">n/a</span> : pct(p.accept)}</td>
                  <td>{insBadge(p)}</td>
                  <td>{p.hmrc === "ok" ? <span className="badge ok">Complete</span> : <span className="badge danger">Missing</span>}</td>
                  <td>{p.status === "Active" ? <span className="badge ok">Active</span> : <span className="badge warn">{p.status}</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <p className="small muted">Providers without complete HMRC details can't be paid out, because platform reporting requires them.</p>
    </>
  );
}

function EstimateScatter() {
  const W = 560, H = 340, P = { l: 46, r: 14, t: 14, b: 42 }, max = 330;
  const x = (v) => P.l + (v / max) * (W - P.l - P.r);
  const y = (v) => H - P.b - (v / max) * (H - P.t - P.b);
  const color = Object.fromEntries(CAL_SEGMENTS.map((s) => [s.id, s.color]));
  const ticks = [0, 60, 120, 180, 240, 300];
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label="Estimated minutes against actual minutes for completed jobs">
      {ticks.map((t) => (
        <g key={t}>
          <line x1={x(0)} x2={x(max)} y1={y(t)} y2={y(t)} style={{ stroke: "var(--hair)" }} />
          <text x={x(0) - 8} y={y(t) + 4} textAnchor="end" className="chart-lbl">{t}</text>
          <text x={x(t)} y={H - P.b + 16} textAnchor="middle" className="chart-lbl">{t}</text>
        </g>
      ))}
      <path d={`M${x(0)} ${y(0)} L${x(max / 1.25)} ${y(max)} L${x(max)} ${y(max)} Z`} style={{ fill: "var(--primary)", opacity: 0.06 }} />
      <line x1={x(0)} y1={y(0)} x2={x(max)} y2={y(max)} style={{ stroke: "var(--muted)", strokeDasharray: "5 5" }} />
      <text x={x(262)} y={y(284)} className="chart-lbl" transform={`rotate(-31 ${x(262)} ${y(284)})`}>Actual = estimate</text>
      {CAL_POINTS.map((p, i) => (
        <circle key={i} cx={x(p.est)} cy={y(Math.min(p.act, max))} r="4.5" style={{ fill: color[p.seg], opacity: 0.85, stroke: "var(--surface)", strokeWidth: 1 }} />
      ))}
      <text x={(x(0) + x(max)) / 2} y={H - 6} textAnchor="middle" className="chart-lbl">Estimated minutes</text>
      <text x={12} y={(y(0) + y(max)) / 2} textAnchor="middle" className="chart-lbl" transform={`rotate(-90 12 ${(y(0) + y(max)) / 2})`}>Actual minutes</text>
    </svg>
  );
}

function AdminCalibration() {
  const notify = useToast();
  const insights = [
    { title: "First cuts take much longer than we estimate",
      body: "Across 14 overgrown or long first cuts, recorded times were 31% above estimate and 57% were countered. The overgrown multiplier looks too low.",
      change: "Raise the overgrown multiplier from 1.9 to 2.4" },
    { title: "Tall hedges are underpriced",
      body: "22 of 29 hedge jobs above head height were countered, by a median of £14. Recorded times are close to estimate, so the rate per metre is the issue, not the time.",
      change: "Raise the above-head rate from 5.5 to 6.5 minutes per metre" },
  ];
  return (
    <>
      <AdminHeader title="Pricing and calibration" sub="Guide prices compared with what jobs actually took. Last 90 days." />
      <div className="kpis">
        {[["Median estimate error", "+6%", "actual vs estimated time"], ["Jobs over by 25%+", "11%", "of timed jobs"],
          ["Taken at guide price", "68%", "of filled jobs"], ["Jobs with a recorded time", "91%", "from the provider timer"]].map(([l, v, s]) => (
          <div key={l} className="card flat kpi"><span className="small muted">{l}</span><div className="v">{v}</div><span className="xs muted">{s}</span></div>
        ))}
      </div>
      <div className="a-cols">
        <div className="card stack" style={{ "--g": "12px" }}>
          <h2 className="h3">Estimated against actual time</h2>
          <EstimateScatter />
          <div className="legend">{CAL_SEGMENTS.map((s) => <span key={s.id}><span className="dot" style={{ background: s.color }} /> {s.label}</span>)}</div>
          <p className="small muted">The shaded band is up to 25% over estimate. Points above it are jobs we underpriced.</p>
        </div>
        <div className="stack" style={{ "--g": "14px" }}>
          {insights.map((ins) => (
            <div key={ins.title} className="card insight stack" style={{ "--g": "10px" }}>
              <h3 className="h3">{ins.title}</h3>
              <p className="small muted">{ins.body}</p>
              <div className="soft small"><b>Suggested:</b> {ins.change}</div>
              <button type="button" className="btn btn-primary btn-sm" style={{ alignSelf: "flex-start" }} onClick={() => notify("Change drafted. It goes live after sign-off.")}>Draft this change</button>
            </div>
          ))}
        </div>
      </div>
      <div className="card">
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Job type</th><th>Jobs</th><th>Taken at guide</th><th>Countered</th><th>Median counter</th><th>Median overrun</th><th>Over by 25%+</th></tr></thead>
            <tbody>
              {CAL_TABLE.map((r) => (
                <tr key={r.seg}>
                  <td><b>{r.seg}</b></td>
                  <td>{r.jobs}</td>
                  <td>{pct(r.guide)}</td>
                  <td>{r.counter > 0.5 ? <span className="badge warn">{pct(r.counter)}</span> : pct(r.counter)}</td>
                  <td>+{fmt(r.uplift)}</td>
                  <td>{r.overrun >= 0.2 ? <span className="badge danger">+{pct(r.overrun)}</span> : `+${pct(r.overrun)}`}</td>
                  <td>{pct(r.over25)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}

function AdminDisputes() {
  const notify = useToast();
  const stages = ["Reported", "Provider replied", "Fix agreed", "Closed"];
  return (
    <>
      <AdminHeader title="Disputes" sub="2 open, 1 closed this month" />
      <div className="soft small row top" style={{ "--g": "10px" }}>
        <Info size={18} style={{ flex: "none", marginTop: 2 }} />
        <span>We mediate; we don't guarantee. The agreement is between customer and provider. Our job is to get it put right, and to remove providers who don't.</span>
      </div>
      <div className="stack" style={{ "--g": "14px" }}>
        {DISPUTES.map((d) => (
          <div key={d.id} className="card stack" style={{ "--g": "14px", opacity: d.stage === 3 ? 0.75 : 1 }}>
            <div className="row between wrap top" style={{ "--g": "10px" }}>
              <div className="row top" style={{ "--g": "12px" }}>
                <span className="cat-ico sm"><CatIcon id={d.cat} size={17} /></span>
                <div className="stack" style={{ "--g": "2px" }}>
                  <h2 className="h3">{d.title}</h2>
                  <span className="small muted">{d.id}, {d.where}, opened {d.opened}. {d.customer} and {d.provider}, {fmt(d.amount)} job.</span>
                </div>
              </div>
              <span className={`badge ${d.stage === 3 ? "ok" : "warn"}`}>{d.status}</span>
            </div>
            <div className="stack" style={{ "--g": "6px" }}>
              <div className="stage" aria-hidden="true">{stages.map((s, i) => <i key={s} className={i <= d.stage ? "on" : ""} />)}</div>
              <div className="row between xs muted">{stages.map((s) => <span key={s}>{s}</span>)}</div>
            </div>
            {d.stage < 3 && (
              <div className="row wrap" style={{ "--g": "8px" }}>
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => notify("Message sent to both")}><MessageCircle size={15} /> Message both</button>
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => notify("Proposed: the provider returns to fix it, free")}>Propose a return visit</button>
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => notify("Proposed: a partial refund, paid by the provider")}>Propose a partial refund</button>
              </div>
            )}
          </div>
        ))}
      </div>
    </>
  );
}

function AdminCategories() {
  const notify = useToast();
  const [selected, setSelected] = useState("mowing");
  const cat = catById(selected);
  const schema = {
    id: cat.id, group: cat.group, status: cat.status, skill: cat.skill,
    pricingModel: cat.pricingModel, ...(cat.pricingParams ? { pricingParams: cat.pricingParams } : {}),
    measure: cat.measure || null, recurring: cat.recurring, requires: cat.requires,
    intake: cat.intake.map((f) => ({
      key: f.key, type: f.type,
      ...(f.options ? { options: f.options.map((o) => o.value) } : {}),
      ...(f.items ? { items: f.items.map((it) => it.key) } : {}),
      ...(f.unit ? { unit: f.unit, min: f.min, max: f.max } : {}),
      default: f.default,
    })),
  };
  return (
    <>
      <AdminHeader title="Categories" sub={`${CATEGORIES.length} live job types. Each is a record, not code: questions, a pricing model and the documents a provider needs.`}
        right={<button type="button" className="btn btn-primary btn-sm" onClick={() => notify("Opens the new category form")}><Plus size={15} /> New category</button>} />
      <div className="a-cols">
        <div className="stack" style={{ "--g": "18px" }}>
          {GROUPS.map((g) => (
            <div key={g.id} className="stack" style={{ "--g": "8px" }}>
              <h2 className="h3">{g.name}</h2>
              {CATEGORIES.filter((c) => c.group === g.id).map((c) => {
                const pool = providersFor(c.id).length;
                return (
                  <button key={c.id} type="button" className={"choice" + (selected === c.id ? " on" : "")} onClick={() => setSelected(c.id)} aria-pressed={selected === c.id}>
                    <span className="cat-ico sm"><CatIcon id={c.id} size={17} /></span>
                    <span className="grow stack" style={{ "--g": "6px" }}>
                      <span className="row between wrap" style={{ "--g": "8px" }}>
                        <b>{c.name}</b>
                        <span className={`badge ${pool >= 2 ? "ok" : pool === 1 ? "warn" : "danger"}`}>{pool} {pool === 1 ? "provider" : "providers"}</span>
                      </span>
                      <span className="req-docs">
                        {c.requires.filter((d) => d !== "insurance").map((d) => <span key={d} className="badge">{DOCS[d]}</span>)}
                        {c.requires.length === 1 && <span className="xs muted">Insurance only</span>}
                      </span>
                    </span>
                  </button>
                );
              })}
            </div>
          ))}
        </div>
        <div className="stack" style={{ "--g": "18px" }}>
          <div className="card stack" style={{ "--g": "12px" }}>
            <div className="row between wrap"><h2 className="h3">{cat.name} record</h2><span className="ident">{cat.pricingModel}</span></div>
            <p className="small muted">The quote flow, provider matching and document checks all render from this.</p>
            <pre className="code">{JSON.stringify(schema, null, 2)}</pre>
          </div>
          <div className="card stack" style={{ "--g": "12px" }}>
            <h2 className="h3">Never listed</h2>
            <p className="small muted">Shown to customers on the home page, with who to use instead.</p>
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Job</th><th>Why not</th></tr></thead>
                <tbody>{EXCLUDED.map((x) => <tr key={x.name}><td><b>{x.name}</b></td><td className="muted">{x.why}</td></tr>)}</tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

/* =========================== Prototype shell =========================== */

const THEMES = [
  { id: "village", name: "Village", swatch: "#1E4B38", note: "Warm and neighbourly" },
  { id: "studio", name: "Studio", swatch: "#E1E4DE", note: "Clean and premium" },
  { id: "toolshed", name: "Toolshed", swatch: "#FF7417", note: "Bold and earthy" },
];
const SURFACES = [["customer", "Customer"], ["provider", "Provider"], ["admin", "Admin"]];
const SCREENS = {
  customer: [["landing", "Home and quote"], ["measure", "Lawn measurement"], ["details", "Job questions"], ["price", "Guide price"],
    ["contact", "Contact and card"], ["offers", "Waiting for providers"], ["booked", "Booking confirmed"], ["account", "My account"], ["rate", "Rate a visit"], ["invite", "Invite from a provider"]],
  provider: [["sms", "Text-message alert"], ["jobs", "New jobs"], ["offer", "Job offer"], ["onjob", "Today's round"], ["finish", "Finish a job"],
    ["earnings", "Earnings"], ["tax", "Tax and records"], ["limit", "Earnings limit"], ["me", "Profile and documents"],
    ["cover", "Time off and helpers"], ["mycustomers", "Your own customers"], ["onboarding", "Sign-up"]],
  admin: [["overview", "Overview and dispatch"], ["providers", "Providers"], ["calibration", "Pricing and calibration"], ["disputes", "Disputes"], ["categories", "Categories"]],
};

export default function App() {
  const [surface, setSurface] = useState("customer");
  const [theme, setTheme] = useState("village");
  const [screens, setScreens] = useState({ customer: "landing", provider: "sms", admin: "overview" });
  const [quote, setQuote] = useState(initialQuote);
  const [toast, setToast] = useState(null);
  const toastTimer = useRef(null);

  const notify = (msg) => {
    setToast(msg);
    clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), 2800);
  };
  const goTo = (s) => (scr) => {
    setScreens((x) => ({ ...x, [s]: scr }));
    if (typeof window !== "undefined" && window.scrollTo) window.scrollTo({ top: 0 });
  };
  const switchTo = (s, scr) => { setSurface(s); if (scr) goTo(s)(scr); };
  useEffect(() => () => clearTimeout(toastTimer.current), []);

  return (
    <div className="pt-shell">
      <style>{CSS}</style>
      <div className="shell-bar">
        <span className="shell-title">{BRAND}<span>front-end prototype</span></span>
        <div className="seg" role="tablist" aria-label="Which side of the product">
          {SURFACES.map(([id, label]) => (
            <button key={id} type="button" role="tab" aria-selected={surface === id} className={surface === id ? "on" : ""} onClick={() => setSurface(id)}>{label}</button>
          ))}
        </div>
        <div className="seg" role="group" aria-label="Visual version">
          {THEMES.map((t) => (
            <button key={t.id} type="button" title={t.note} aria-pressed={theme === t.id} className={theme === t.id ? "on" : ""} onClick={() => setTheme(t.id)}>
              <span className="swatch" style={{ background: t.swatch }} />{t.name}
            </button>
          ))}
        </div>
        <select className="shell-select" aria-label="Jump to screen" value={screens[surface]} onChange={(e) => goTo(surface)(e.target.value)}>
          {SCREENS[surface].map(([id, label]) => <option key={id} value={id}>{label}</option>)}
        </select>
      </div>
      <ToastCtx.Provider value={notify}>
        <div className="pt" data-theme={theme}>
          <div hidden={surface !== "customer"}>
            <CustomerApp screen={screens.customer} go={goTo("customer")} theme={theme} quote={quote} setQuote={setQuote} switchTo={switchTo} />
          </div>
          <div hidden={surface !== "provider"}>
            <ProviderApp screen={screens.provider} go={goTo("provider")} />
          </div>
          <div hidden={surface !== "admin"}>
            <AdminApp screen={screens.admin} go={goTo("admin")} />
          </div>
          {toast && <div className="toast" role="status">{toast}</div>}
        </div>
      </ToastCtx.Provider>
    </div>
  );
}
