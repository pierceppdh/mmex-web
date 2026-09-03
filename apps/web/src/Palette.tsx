import { useEffect, useMemo, useRef, useState } from "react";
import type { MessageKey } from "./i18n";

export type PaletteCommand = {
  id: string;
  label: string;
  disabled?: boolean;
  run: () => void;
};

type Props = {
  open: boolean;
  commands: PaletteCommand[];
  t: (key: MessageKey) => string;
  onClose: () => void;
};

export function Palette({ open, commands, t, onClose }: Props) {
  const [query, setQuery] = useState("");
  const [index, setIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return commands;
    return commands.filter((c) => c.label.toLowerCase().includes(q));
  }, [commands, query]);

  useEffect(() => {
    if (open) {
      setQuery("");
      setIndex(0);
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  useEffect(() => {
    setIndex(0);
  }, [query]);

  if (!open) return null;

  function choose(cmd: PaletteCommand) {
    if (cmd.disabled) return;
    cmd.run();
    onClose();
  }

  return (
    <div className="palette-backdrop" onClick={onClose} role="presentation">
      <div
        className="palette"
        role="dialog"
        aria-label={t("commandPalette")}
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          if (e.key === "Escape") onClose();
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setIndex((i) => Math.min(i + 1, Math.max(filtered.length - 1, 0)));
          }
          if (e.key === "ArrowUp") {
            e.preventDefault();
            setIndex((i) => Math.max(i - 1, 0));
          }
          if (e.key === "Enter") {
            e.preventDefault();
            const cmd = filtered[index];
            if (cmd) choose(cmd);
          }
        }}
      >
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t("paletteHint")}
        />
        <ul>
          {filtered.length === 0 && <li className="k">{t("paletteEmpty")}</li>}
          {filtered.map((cmd, i) => (
            <li key={cmd.id}>
              <button
                type="button"
                className={i === index ? "active" : ""}
                disabled={cmd.disabled}
                onMouseEnter={() => setIndex(i)}
                onClick={() => choose(cmd)}
              >
                {cmd.label}
                {cmd.disabled ? ` — ${t("comingSoon")}` : ""}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
