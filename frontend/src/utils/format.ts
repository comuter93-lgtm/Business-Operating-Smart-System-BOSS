const inrFormatter = new Intl.NumberFormat("en-IN", {
  maximumFractionDigits: 2,
  minimumFractionDigits: 0,
});

export function formatINR(value: string | number | undefined | null): string {
  if (value === undefined || value === null || value === "") return "₹0";
  const num = Number(value);
  if (Number.isNaN(num)) return `₹${value}`;
  return `₹${inrFormatter.format(num)}`;
}

export function formatDateShort(iso: string | undefined | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

