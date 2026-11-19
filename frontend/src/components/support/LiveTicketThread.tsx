"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, CheckCircle2, Share2, UserCheck } from "lucide-react";
import { api } from "@/lib/api";
import { ReplyBox, StatusBadge, Thread, TypingDots } from "@/components/support/TicketThread";
import { useSupportSocket } from "@/components/support/useSupportSocket";
import SharePicker from "@/components/support/SharePicker";

/**
 * FR-C203: the panel's live thread. Fetches the ticket once via the
 * existing REST GET (history + ownership + current status - the WS
 * connection carries no history of its own, Rules.md), then layers
 * useSupportSocket's live messages on top; never trusts the socket as the
 * only source of truth (Non_Functional_Requirements.md's Reliability gate -
 * FR-C206 adds the reconnect/re-fetch half of that, this FR already never
 * relies on the socket alone for the initial state).
 */
export default function LiveTicketThread({
  ticketId, onBack, forStaff = false, onTicketChanged, guestToken = null,
}: {
  ticketId: string;
  onBack: () => void;
  /** FR-C302: same component, for_staff mode - customer identity,
   * assignment, and the Take it/Resolve actions SupportTab.tsx's own
   * static view already had. */
  forStaff?: boolean;
  /** Lets a staff-side caller (SupportTab.tsx) refresh its own queue list
   * right after an action here, in addition to whatever FR-C301's queue
   * socket eventually delivers. */
  onTicketChanged?: () => void;
  /** FR-C404: when set, this thread belongs to a not-logged-in visitor -
   * every REST call and the WS connection use this guest_token instead of
   * the JWT in localStorage (docs/Architecture.md "Guest chat"). Staff
   * actions (forStaff) never apply in guest mode - a guest viewing their
   * own ticket is never staff. */
  guestToken?: string | null;
}) {
  const [ticket, setTicket] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    if (guestToken) {
      setTicket(await api.getGuestTicket(ticketId, guestToken));
      return;
    }
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    setTicket(await api.getTicket(token, ticketId));
  }, [ticketId, guestToken]);

  // FR-C206: re-fetch on reconnect so a message sent by the other side
  // while this socket was dropped isn't silently missed (Reliability gate,
  // Non_Functional_Requirements.md) - the socket is never trusted as the
  // only source of truth, same reasoning as the initial load above.
  const onReconnect = useCallback(() => {
    load().catch(() => {
      // A reconnect is best-effort by nature; the next successful one
      // (or a manual refresh, surfaced below while disconnected) tries again.
    });
  }, [load]);
  const { messages: liveMessages, typingFrom, sendTyping, connected } = useSupportSocket(ticketId, onReconnect, guestToken);

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
    const token = guestToken ? null : localStorage.getItem("esim_token");
    if (!token && !guestToken) return;
    setSending(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("body", body);
      files.forEach((f) => form.append("files", f));
      if (guestToken) {
        form.append("guest_token", guestToken);
        setTicket(await api.replyAsGuest(ticketId, form));
      } else {
        setTicket(await api.replyToTicket(token as string, ticketId, form));
      }
      onTicketChanged?.();
    } catch (err: any) {
      setError(err.message || "Couldn't send that");
    } finally {
      setSending(false);
    }
  };

  // FR-C205: a share is its own message (ORDER_SHARE/PRODUCT_SHARE), posted
  // through the exact same REST endpoint as a text reply - no new API
  // client method, no second code path. Ownership is enforced server-side
  // (support_svc._check_shared_order/_check_shared_product), not trusted
  // from the picker alone. Guests never reach this: the share button is
  // hidden below when guestToken is set (a guest can't share an order -
  // support_svc.post_message rejects it - and a product share isn't
  // offered either, to keep the guest compose flow to the one thing it's
  // for: asking a question before signing up).
  const sendShare = async (selection: { kind: "order"; orderId: string } | { kind: "product"; productId: string }) => {
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    setSharing(false);
    setSending(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("body", "");
      if (selection.kind === "order") form.append("shared_order_id", selection.orderId);
      else form.append("shared_product_id", selection.productId);
      setTicket(await api.replyToTicket(token, ticketId, form));
      onTicketChanged?.();
    } catch (err: any) {
      setError(err.message || "Couldn't share that");
    } finally {
      setSending(false);
    }
  };

  // FR-C302: the same two staff actions SupportTab.tsx's static view
  // already had - reused here, not reimplemented.
  const [acting, setActing] = useState(false);
  const act = async (fn: (token: string, id: string) => Promise<any>) => {
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    setActing(true);
    setError(null);
    try {
      await fn(token, ticketId);
      await load();
      onTicketChanged?.();
    } catch (err: any) {
      setError(err.message || "Couldn't do that");
    } finally {
      setActing(false);
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
          {forStaff && (
            <div className="text-[10px] text-slate-500 mt-0.5 truncate">
              {ticket.customer?.username} · {ticket.customer?.email}
              {ticket.assigned_to ? <> · assigned to <strong>{ticket.assigned_to}</strong></> : null}
            </div>
          )}
        </div>
        <div className="flex flex-col items-end gap-1.5 shrink-0">
          <StatusBadge status={ticket.status} staff={forStaff} />
          {forStaff && (
            <div className="flex gap-1.5">
              {!ticket.assigned_to && (
                <button
                  type="button"
                  onClick={() => act(api.assignTicket)}
                  disabled={acting}
                  className="inline-flex items-center gap-1 bg-white hover:bg-gray-50 border border-gray-300 text-slate-700 text-[10px] font-bold px-2 py-1 rounded-lg disabled:opacity-50"
                >
                  <UserCheck className="w-3 h-3" /> Take it
                </button>
              )}
              {ticket.status !== "RESOLVED" && ticket.status !== "CLOSED" && (
                <button
                  type="button"
                  onClick={() => act(api.resolveTicket)}
                  disabled={acting}
                  className="inline-flex items-center gap-1 bg-emerald-600 hover:bg-emerald-500 text-white text-[10px] font-bold px-2 py-1 rounded-lg disabled:opacity-50"
                >
                  <CheckCircle2 className="w-3 h-3" /> Resolve
                </button>
              )}
            </div>
          )}
        </div>
      </div>

      {/* FR-C206: never a hard error that blocks viewing/sending
          (Non_Functional_Requirements.md) - just a visible notice plus a
          manual way to catch up while the socket reconnects on its own. */}
      {!connected && (
        <div className="px-4 py-2 bg-amber-50 border-b border-amber-100 flex items-center justify-between gap-2 shrink-0">
          <span className="text-[11px] text-amber-800">Live updates paused - reconnecting…</span>
          <button
            type="button"
            onClick={() => load().catch(() => {})}
            className="text-[11px] font-bold text-amber-900 underline shrink-0"
          >
            Refresh
          </button>
        </div>
      )}

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

      <div className="p-4 border-t border-gray-100 shrink-0 relative">
        {sharing && (
          <div className="absolute bottom-full left-4 right-4 mb-2">
            <SharePicker onSelect={sendShare} onClose={() => setSharing(false)} />
          </div>
        )}
        {!closed && !guestToken && (
          <button
            type="button"
            onClick={() => setSharing((v) => !v)}
            aria-expanded={sharing}
            className="inline-flex items-center gap-1.5 mb-2 rounded-xl border border-gray-300 bg-white px-3 py-1.5 text-[11px] font-semibold text-slate-600 hover:bg-gray-50"
          >
            <Share2 className="w-3.5 h-3.5" /> Share an order or package
          </button>
        )}
        <ReplyBox
          onSend={send}
          sending={sending}
          disabled={closed}
          onTyping={sendTyping}
          placeholder={forStaff ? "Reply to the customer…" : "Write a reply…"}
        />
        {forStaff && (
          <p className="mt-2 text-[11px] text-slate-400">
            The customer sees this as &ldquo;Support&rdquo; — your username isn&apos;t shown to them.
          </p>
        )}
      </div>
    </div>
  );
}
