/**
 * The quote flow's state, shared by the landing page and /quote/:categoryId/* (size, details,
 * price, contact). Kept in sessionStorage so a reload doesn't lose the answers; photos the
 * customer picks stay in memory (files can't be stored) until they're uploaded with the request.
 */
import { createContext, useContext } from "react";
import type { Address, Category } from "./api";

export type Adjust = "smaller" | "right" | "bigger";
export type Days = "any" | "weekdays" | "weekends";
export type Time = "morning" | "afternoon" | "either";
export type Answers = Record<string, unknown>;

export type FlowState = {
  categoryId: string;
  address: Address | null;
  addressText: string;
  lawn: { band: string | null; adjust: Adjust };
  answers: Record<string, Answers>;
  notes: string;
  when: { days: Days; time: Time };
  contact: { name: string; phone: string; email: string };
  quoteId: string | null;
};

export const INITIAL_FLOW: FlowState = {
  categoryId: "mowing",
  address: null,
  addressText: "",
  lawn: { band: null, adjust: "right" },
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
    return raw ? { ...INITIAL_FLOW, ...(JSON.parse(raw) as Partial<FlowState>) } : INITIAL_FLOW;
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
