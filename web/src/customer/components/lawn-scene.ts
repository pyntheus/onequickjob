/**
 * The geometry of the size step's lawn drawings (decisions.md A26), in metres. LawnDrawing.tsx
 * draws it.
 *
 * Every drawing's viewBox is SCENE_W metres across and is drawn at the full width of a
 * .lawn-cell, and every .lawn-cell is the same width (.lawn-grid), so all drawings share one
 * metres-to-pixels scale: the four bands' sizes compare truly, and so does the lawn the customer
 * paced out or measured beside them. Lawns too big for the scene are drawn smaller, with the car
 * and person shrunk to match (sceneFactor below 1; the page says so).
 */

/** Metres across every drawing: Very large (23 m) beside a house (7 m), with margins. */
export const SCENE_W = 33;
export const PAD = 0.8;
export const CAR = { l: 4.5, w: 1.8 };
export const HOUSE = { w: 7, d: 9 };
export const PERSON_H = 1.75;
export const LABEL = 1.25; // text size, in metres of the drawing
const GAP = 1.5; // lawn to house
const ROW_GAP = 1.4; // lawns to the car
const LAWN_GAP = 1.2; // between lawns
const HOUSE_LABEL = 3.1; // "A house, / for scale" under the house
const MAX_H = 36; // a drawing taller than this (in metres) is drawn smaller

/** A lawn as the API gives it; `text` is written on it if it fits. */
export type LawnRect = { length_m: number; width_m: number; text?: string };
export type PlacedLawn = { x: number; y: number; across: number; down: number; text?: string; name?: string };
export type Scene = {
  f: number;
  height: number;
  lawns: PlacedLawn[];
  house: { x: number; y: number } | null;
  car: { x: number; y: number };
  person: { x: number; base: number };
};

/** The scale of a drawing of these lawns: 1 when they fit the shared scale, less when not. */
export function sceneFactor(lawns: LawnRect[]): number {
  const longest = Math.max(CAR.l + 2, ...lawns.map((l) => Math.max(l.length_m, l.width_m)));
  const tall = lawns.reduce((t, l) => t + Math.min(l.length_m, l.width_m), 0) + LAWN_GAP * (lawns.length - 1);
  const labels = lawns.length > 1 ? lawns.length * (LABEL + 0.4) : 0;
  return Math.min(1, (SCENE_W - 2 * PAD) / longest, (MAX_H - labels - ROW_GAP - PERSON_H - 2 * PAD) / tall);
}

/** Lawns stacked down the left, each with its long side across (named "Lawn 1"... if there
 * are several and `names`), a house beside the first if asked, then a car and a person. */
export function layoutScene(lawns: LawnRect[], house: boolean, names: boolean): Scene {
  const f = sceneFactor(lawns);
  const named = names && lawns.length > 1;
  const placed: PlacedLawn[] = [];
  let y = PAD;
  lawns.forEach((l, i) => {
    if (named) y += LABEL + 0.4;
    const across = Math.max(l.length_m, l.width_m) * f;
    const down = Math.min(l.length_m, l.width_m) * f;
    placed.push({ x: PAD, y, across, down, text: l.text, name: named ? `Lawn ${i + 1}` : undefined });
    y += down + LAWN_GAP;
  });
  const lawnsBottom = y - LAWN_GAP;
  const houseAt = house ? { x: PAD + (placed[0]?.across ?? 0) + GAP, y: PAD } : null;
  const rowTop = Math.max(lawnsBottom, houseAt ? PAD + HOUSE.d + HOUSE_LABEL : 0) + ROW_GAP * Math.max(f, 0.6);
  const carY = rowTop + Math.max(0, PERSON_H - CAR.w) * f;
  const base = carY + CAR.w * f;
  return {
    f,
    height: base + PAD,
    lawns: placed,
    house: houseAt,
    car: { x: PAD, y: carY },
    person: { x: PAD + CAR.l * f + 1.1 * Math.max(f, 0.6), base },
  };
}
