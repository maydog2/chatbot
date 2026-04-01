"use client";

import { useEffect, useRef, useState } from "react";

export type GamesMenuProps = {
  tr: (key: string) => string;
  /** Normal chat composer vs compact in-game composer (different labels / classes). */
  variant: "chat" | "gomoku";
  onPickGomoku: () => void;
};

/** In-chat games dropdown (currently Gomoku). Owns open state and outside-click handling. */
export function GamesMenu({ tr, variant, onPickGomoku }: GamesMenuProps) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("click", onDocClick, true);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("click", onDocClick, true);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const wrapClass = variant === "gomoku" ? "send-games-wrap send-games-wrap--gomoku" : "send-games-wrap";
  const btnClass = variant === "gomoku" ? "send-games-btn send-games-btn--gomoku" : "send-games-btn";

  return (
    <div className={wrapClass} ref={wrapRef}>
      <button
        type="button"
        className={btnClass}
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-label={variant === "gomoku" ? tr("games.switchGamesAria") : tr("games.menuAria")}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
      >
        <span className="send-games-btn-emoji" aria-hidden>
          🎮
        </span>
        {variant === "gomoku" ? tr("games.switchGames") : tr("games.menu")}
      </button>
      {open && (
        <div className="send-games-dropdown" role="listbox">
          <button
            type="button"
            role="option"
            className="send-games-dropdown-item"
            onClick={() => {
              setOpen(false);
              onPickGomoku();
            }}
          >
            {tr("games.gomoku")}
          </button>
        </div>
      )}
    </div>
  );
}
