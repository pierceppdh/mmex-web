export type SortState = { key: string; dir: "asc" | "desc" };

export function toggleSort(prev: SortState, key: string): SortState {
  if (prev.key === key) return { key, dir: prev.dir === "asc" ? "desc" : "asc" };
  return { key, dir: "asc" };
}

export function compareValues(a: unknown, b: unknown): number {
  const sa = String(a ?? "").trim();
  const sb = String(b ?? "").trim();
  const na = Number(sa.replace(/\s/g, "").replace(",", "."));
  const nb = Number(sb.replace(/\s/g, "").replace(",", "."));
  if (sa !== "" && sb !== "" && !Number.isNaN(na) && !Number.isNaN(nb)) return na - nb;
  return sa.localeCompare(sb, undefined, { numeric: true, sensitivity: "base" });
}

export function sortBy<T>(
  rows: T[],
  sort: SortState,
  get: (row: T, key: string) => unknown,
): T[] {
  const mul = sort.dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => mul * compareValues(get(a, sort.key), get(b, sort.key)));
}

type ThProps = {
  label: string;
  k: string;
  sort: SortState;
  onSort: (key: string) => void;
  className?: string;
};

export function SortTh({ label, k, sort, onSort, className }: ThProps) {
  const on = sort.key === k;
  return (
    <th className={className}>
      <button type="button" className="th-sort" onClick={() => onSort(k)}>
        {label}
        <span className="th-ind" aria-hidden>
          {on ? (sort.dir === "asc" ? "▲" : "▼") : ""}
        </span>
      </button>
    </th>
  );
}
