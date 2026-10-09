/** Show a transaction amount with exactly two decimal places. */
export function cents(value: string | number | null | undefined): string {
  if (value == null || value === "") return "";
  const cleaned = String(value).trim().replace(/\s/g, "").replace(",", ".");
  if (!cleaned) return "";
  const amount = Number(cleaned);
  if (!Number.isFinite(amount)) return String(value);
  return amount.toFixed(2);
}
