import { useEffect, useId, useState } from "react";
import { api } from "./api";
import type { MessageKey } from "./i18n";
import type { Payee } from "./types";

export async function resolvePayeeId(query: string, fallback = 0): Promise<number | undefined> {
  if (fallback > 0) return fallback;
  const q = query.trim();
  if (!q) return undefined;
  const r = await api.get<{ payees: Payee[] }>(`/api/payees?q=${encodeURIComponent(q)}&limit=40`);
  return r.payees.find((p) => p.name.toLowerCase() === q.toLowerCase())?.payee_id;
}

type Props = {
  value: string;
  payeeId: number;
  t: (key: MessageKey) => string;
  required?: boolean;
  listId?: string;
  onChange: (query: string, payeeId: number, match: Payee | undefined) => void;
};

export function PayeeField({ value, payeeId, t, required, listId, onChange }: Props) {
  const autoId = useId();
  const id = listId ?? autoId;
  const [payees, setPayees] = useState<Payee[]>([]);

  useEffect(() => {
    const q = value.trim();
    const handle = window.setTimeout(() => {
      const path = q
        ? `/api/payees?q=${encodeURIComponent(q)}&limit=40`
        : "/api/payees?limit=40";
      void api.get<{ payees: Payee[] }>(path).then((r) => setPayees(r.payees));
    }, 200);
    return () => window.clearTimeout(handle);
  }, [value]);

  return (
    <label>
      <span>{t("payee")}</span>
      <input
        list={id}
        value={value}
        required={required}
        onChange={(e) => {
          const name = e.target.value;
          const match = payees.find((p) => p.name.toLowerCase() === name.trim().toLowerCase());
          onChange(name, match?.payee_id ?? (name.trim() ? 0 : payeeId), match);
        }}
      />
      <datalist id={id}>
        {payees.map((p) => (
          <option key={p.payee_id} value={p.name} />
        ))}
      </datalist>
    </label>
  );
}
