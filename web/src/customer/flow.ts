/**
 * The quote flow's state, shared by the landing page and /quote/:categoryId/* (size, details,
 * price, contact). Kept in sessionStorage so a reload doesn't lose the answers; photos the
 * customer picks stay in memory (files can't be stored) until they're uploaded with the request.
 */
import { createContext, useContext } from "react";
import type { Schemas } from "../api/client";
import { DECIMAL, WHOLE } from "../shared/number-text";
import type { Address, Category } from "./api";

export type Adjust = "smaller" | "right" | "bigger";
/** The lawn step's three ways (decisions.md A26): a size band, paced out, or measured. */
export type LawnMethod = "band" | "paced" | "measured";
export type LengthUnit = "m" | "ft";
/** One lawn's sides as typed: strides (paced) or metres or feet (measured). Kept as text, so
 * "7.50" stays what the customer typed; the API works the area out. */
export type LawnSides = { length: string; width: string };
export type LawnState = {
  method: LawnMethod;
  band: string | null;
  adjust: Adjust;
  unit: LengthUnit;
  paced: LawnSides[];
  measured: LawnSides[];
};
export type Days = "any" | "weekdays" | "weekends";
export type Time = "morning" | "afternoon" | "either";
export type Answers = Record<string, unknown>;

export type FlowState = {
  categoryId: string;
  address: Address | null;
  addressText: string;
  lawn: LawnState;
  answers: Record<string, Answers>;
  notes: string;
  when: { days: Days; time: Time };
  contact: { name: string; phone: string; email: string };
  quoteId: string | null;
};

export const EMPTY_LAWN: LawnSides = { length: "", width: "" };
export const INITIAL_LAWN: LawnState = {
  method: "band",
  band: null,
  adjust: "right",
  unit: "m",
  paced: [EMPTY_LAWN],
  measured: [EMPTY_LAWN],
};

export const INITIAL_FLOW: FlowState = {
  categoryId: "mowing",
  address: null,
  addressText: "",
  lawn: INITIAL_LAWN,
  answers: {},
  notes: "",
  when: { days: "weekdays", time: "morning" },
  contact: { name: "", phone: "", email: "" },
  quoteId: null,
};

export const FLOW_KEY = "oqj.quote-flow.v1";

export function loadFlow(): FlowState {
  try {
    const raw = sessionStorage.getItem(FLOW_KEY);
    if (!raw) return INITIAL_FLOW;
    const saved = JSON.parse(raw) as Partial<FlowState>;
    // A flow saved before the three ways (A26) has only band and adjust: fill in the rest.
    return { ...INITIAL_FLOW, ...saved, lawn: { ...INITIAL_LAWN, ...(saved.lawn ?? {}) } };
  } catch {
    return INITIAL_FLOW;
  }
}

export type FlowCtxValue = {
  flow: FlowState;
  update: (patch: Partial<FlowState> | ((f: FlowState) => Partial<FlowState>)) => void;
  photos: Record<string, File[]>;
  setPhotos: (key: string, files: File[]) => void;
  reset: () => void;
};

export const FlowCtx = createContext<FlowCtxValue | null>(null);

export function useFlow(): FlowCtxValue {
  const ctx = useContext(FlowCtx);
  if (!ctx) throw new Error("useFlow outside FlowProvider");
  return ctx;
}

/** The answers for a category: its intake defaults, overlaid with what the customer chose. */
export function answersFor(cat: Category, flow: FlowState): Answers {
  const defaults = Object.fromEntries(cat.intake.map((f) => [f.key, f.default]));
  return { ...defaults, ...(flow.answers[cat.id ?? ""] ?? {}) };
}

/** What goes to POST /api/quotes: photos travel with the request, not the quote. */
export function quoteAnswers(cat: Category, flow: FlowState): Answers {
  const all = answersFor(cat, flow);
  for (const f of cat.intake) if (f.type === "photos") all[f.key] = [];
  return all;
}

/** The flow's steps for a category: lawns have a size step first. */
export function stepsFor(cat: Pick<Category, "measure">): string[] {
  return cat.measure ? ["size", "details", "price", "contact"] : ["details", "price", "contact"];
}

export function emptyCounts(cat: Category, answers: Answers): boolean {
  return cat.intake.some(
    (f) => f.type === "counts" && Object.values((answers[f.key] as Record<string, number>) ?? {}).every((n) => !n),
  );
}

/** The lawns the chosen way is working with (paced or measured). */
export function lawnsOf(lawn: LawnState): LawnSides[] {
  return lawn.method === "measured" ? lawn.measured : lawn.paced;
}

/** Has the customer given everything the chosen way needs? (Whether it's a valid size is the API's call.) */
export function lawnFilled(lawn: LawnState): boolean {
  if (lawn.method === "band") return !!lawn.band;
  return lawnsOf(lawn).every((l) => l.length.trim() !== "" && l.width.trim() !== "");
}

export type BadSide = { lawn: number; side: keyof LawnSides; message: string };

/** The first side typed that isn't a number the chosen way takes (whole strides; metres or feet
 * with up to two decimal places), so it's never sent as some other number. Whether the sizes are
 * in range is the API's call. */
export function badSide(lawn: LawnState): BadSide | null {
  if (lawn.method === "band") return null;
  const lawns = lawnsOf(lawn);
  for (const [i, l] of lawns.entries()) {
    for (const side of ["length", "width"] as const) {
      const text = l[side].trim();
      if (text === "" || (lawn.method === "paced" ? WHOLE : DECIMAL).test(text)) continue;
      const what = lawns.length > 1 ? `Lawn ${i + 1}: the ${side}` : `The ${side}`;
      const message =
        lawn.method === "paced"
          ? `${what} is a whole number of strides, like 12.`
          : `${what} needs to be a number like 7.5, with up to two decimal places.`;
      return { lawn: i, side, message };
    }
  }
  return null;
}

/** Filled in, and every side a number the chosen way takes: ready to be priced. */
export function lawnReady(lawn: LawnState): boolean {
  return lawnFilled(lawn) && badSide(lawn) === null;
}

/** The lawn step's answer as the API takes it (POST /api/area/estimate and /api/quotes). */
export function lawnInput(lawn: LawnState): Schemas["AreaInput"] {
  if (lawn.method === "band") return { method: "band", band: lawn.band, adjust: lawn.adjust, unit: "m" };
  return {
    method: lawn.method,
    adjust: "right",
    unit: lawn.method === "measured" ? lawn.unit : "m",
    lawns: lawnsOf(lawn).map((l) => ({ length: l.length.trim(), width: l.width.trim() })),
  };
}
