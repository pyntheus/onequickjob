/** What a typed number field may hold: whole numbers, or at most two decimal places ("7.5"). */
export const WHOLE = /^\d+$/;
export const DECIMAL = /^\d+(\.\d{1,2})?$/;

/** The whole number typed, or null if the text isn't one (" 45 " is 45; "45.5", "4e1" and "" aren't). */
export function wholeNumber(text: string): number | null {
  const t = text.trim();
  return WHOLE.test(t) ? Number(t) : null;
}
