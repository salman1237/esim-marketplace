"use client";

import React, { useEffect, useRef, useState } from "react";
import { AlertCircle, Check, Loader2 } from "lucide-react";

type Props = {
  /** The rate currently stored on the server. */
  value: number | string;
  /** Resolves when the new rate is persisted; rejects with a message if not. */
  onSave: (rate: number) => Promise<void>;
  disabled?: boolean;
};

/**
 * One merchant's commission rate, saved in place.
 *
 * There is no Save button here by design - a table of them would be noise -
 * but "no button" only works if the field says what it did. Previously it
 * committed silently on blur and spoke up only to complain, so a successful
 * save and a change that never left the browser looked identical. Worse, a
 * failed save left the typed number sitting in the box as though it had
 * stuck.
 *
 * So: Enter commits, Escape abandons, every outcome is visible, and a
 * rejected save puts the stored value back rather than leaving a figure on
 * screen that nothing agreed to.
 */
export default function CommissionCell({ value, onSave, disabled }: Props) {
  const stored = String(value);
  const [draft, setDraft] = useState(stored);
  const [state, setState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [message, setMessage] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const savedTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Escape has to suppress the save that blurring would otherwise trigger.
  // Resetting the draft first does not help: setState is queued, so the blur
  // handler still sees the typed value and commits the very edit Escape was
  // meant to abandon.
  const abandonRef = useRef(false);

  // Follow the server's value when it changes underneath us (a reload, or
  // another admin editing the same merchant).
  useEffect(() => {
    setDraft(stored);
  }, [stored]);

  useEffect(() => () => {
    if (savedTimer.current) clearTimeout(savedTimer.current);
  }, []);

  const commit = async () => {
    if (state === "saving") return;
    const typed = draft.trim();
    if (typed === stored) {
      setState("idle");
      setMessage(null);
      return;
    }

    const rate = parseFloat(typed);
    if (typed === "" || Number.isNaN(rate) || rate < 0 || rate > 100) {
      setDraft(stored);
      setState("error");
      setMessage("Must be 0–100");
      return;
    }

    setState("saving");
    setMessage(null);
    try {
      await onSave(rate);
      setState("saved");
      if (savedTimer.current) clearTimeout(savedTimer.current);
      savedTimer.current = setTimeout(() => setState("idle"), 2200);
    } catch (err: any) {
      // Put the stored rate back. Leaving the typed one would show a number
      // the server never accepted, which is the one thing worse than silence.
      setDraft(stored);
      setState("error");
      setMessage(err?.message || "Not saved");
    }
  };

  if (disabled) return <span className="text-slate-700">{stored}%</span>;

  return (
    <div className="flex items-center gap-1.5">
      <div className="relative">
        <input
          ref={inputRef}
          type="number"
          min={0}
          max={100}
          step={0.01}
          value={draft}
          disabled={state === "saving"}
          onChange={(e) => {
            setDraft(e.target.value);
            if (state !== "idle") {
              setState("idle");
              setMessage(null);
            }
          }}
          onBlur={() => {
            if (abandonRef.current) {
              abandonRef.current = false;
              return;
            }
            commit();
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              // Blur rather than calling commit directly, so pressing Enter
              // and clicking away cannot both fire the same save.
              inputRef.current?.blur();
            } else if (e.key === "Escape") {
              e.preventDefault();
              abandonRef.current = true;
              setDraft(stored);
              setState("idle");
              setMessage(null);
              inputRef.current?.blur();
            }
          }}
          className={`w-20 bg-white border rounded px-2 py-1 pe-6 text-xs text-slate-900 transition-colors ${
            state === "error"
              ? "border-rose-300 bg-rose-50"
              : state === "saved"
              ? "border-emerald-300 bg-emerald-50"
              : "border-gray-300"
          }`}
        />
        <span className="absolute end-1.5 top-1/2 -translate-y-1/2 pointer-events-none">
          {state === "saving" && <Loader2 className="w-3 h-3 text-slate-400 animate-spin" />}
          {state === "saved" && <Check className="w-3 h-3 text-emerald-600" />}
          {state === "error" && <AlertCircle className="w-3 h-3 text-rose-600" />}
        </span>
      </div>

      {state === "saved" && <span className="text-[10px] font-semibold text-emerald-600">Saved</span>}
      {state === "error" && message && (
        <span className="text-[10px] font-semibold text-rose-600 max-w-[140px] truncate" title={message}>
          {message}
        </span>
      )}
      {state === "idle" && draft.trim() !== stored && (
        <span className="text-[10px] text-slate-400">Enter to save</span>
      )}
    </div>
  );
}
