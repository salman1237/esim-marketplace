"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft } from "lucide-react";
import { api } from "@/lib/api";
import { ReplyBox, StatusBadge, Thread, TypingDots } from "@/components/support/TicketThread";
import { useSupportSocket } from "@/components/support/useSupportSocket";

/**
 * FR-C203: the panel's live thread. Fetches the ticket once via the
 * existing REST GET (history + ownership + current status - the WS
 * connection carries no history of its own, Rules.md), then layers
 * useSupportSocket's live messages on top; never trusts the socket as the
 * only source of truth (Non_Functional_Requirements.md's Reliability gate -
 * FR-C206 adds the reconnect/re-fetch half of that, this FR already never
 * relies on the socket alone for the initial state).
 */
export default function LiveTicketThread({ ticketId, onBack }: { ticketId: string; onBack: () => void }) {
  const [ticket, setTicket] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const { messages: liveMessages, typingFrom, sendTyping } = useSupportSocket(ticketId);

  const load = useCallback(async () => {
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    setTicket(await api.getTicket(token, ticketId));
  }, [ticketId]);

  useEffect(() => {
    setLoading(true);
    load()
      .catch((err) => setError(err.message || "Couldn't load this ticket"))
      .finally(() => setLoading(false));
  }, [load]);

  // The REST fetch is the source of truth for everything up to the moment
  // it ran; the socket only ever adds what arrived after - dedupe by id so
  // a message doesn't appear twice if both happen to carry it.
  const allMessages = useMemo(() => {
    const base = ticket?.messages || [];
    const seen = new Set(base.map((m: any) => m.id));
    const extra = liveMessages.filter((m) => !seen.has(m.id));
    return [...base, ...extra];
  }, [ticket, liveMessages]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [allMessages.length]);

  const send = async (body: string, files: File[]) => {
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    setSending(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("body", body);
      files.forEach((f) => form.append("files", f));
      setTicket(await api.replyToTicket(token, ticketId, form));
    } catch (err: any) {
      setError(err.message || "Couldn't send that");
    } finally {
      setSending(false);
    }
  };

  if (loading) {
    return (
      <div className="p-4 space-y-3">
        <div className="h-6 w-40 rounded bg-gray-100 animate-pulse" />
        <div className="h-48 rounded-2xl bg-gray-100 animate-pulse" />
      </div>
    );
  }

  if (!ticket) {
    return (
      <div className="p-4 text-center text-xs text-slate-500">
        {error || "That ticket could not be found."}
        <button onClick={onBack} className="block mx-auto mt-3 text-xs font-bold text-brand-600 underline">
          Back to your tickets
        </button>
      </div>
    );
  }

  const closed = ticket.status === "CLOSED";

  return (
    <div className="flex flex-col h-full">
      <div className="px-4 py-3 border-b border-gray-100 flex items-start justify-between gap-2 shrink-0">
        <button
          type="button"
          onClick={onBack}
          aria-label="Back to your tickets"
          className="inline-flex items-center gap-1 text-[11px] font-semibold text-slate-500 hover:text-slate-900 mt-0.5"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
        </button>
        <div className="min-w-0 flex-1">
          <div className="text-xs font-bold text-slate-900 truncate">{ticket.subject}</div>
          <div className="text-[10px] text-slate-400 font-mono">{ticket.reference}</div>
        </div>
        <StatusBadge status={ticket.status} />
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {error && <p className="mb-3 text-xs text-rose-600">{error}</p>}
        <Thread messages={allMessages} />
        {typingFrom && (
          <div className={`mt-3 flex ${typingFrom === "staff" ? "justify-start" : "justify-end"}`}>
            <div className="rounded-2xl px-3 py-2 border border-gray-200 bg-white">
              <TypingDots />
            </div>
          </div>
        )}
        {/* Screen-reader announcement alongside the visual dots above
            (Non_Functional_Requirements.md's Accessibility gate - "not
            purely a visual animation"). */}
        <div aria-live="polite" className="sr-only">
          {typingFrom ? `${typingFrom === "staff" ? "Support" : "Customer"} is typing…` : ""}
        </div>
        <div ref={bottomRef} />
      </div>

      <div className="p-4 border-t border-gray-100 shrink-0">
        <ReplyBox onSend={send} sending={sending} disabled={closed} onTyping={sendTyping} />
      </div>
    </div>
  );
}
