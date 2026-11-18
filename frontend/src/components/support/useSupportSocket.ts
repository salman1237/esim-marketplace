"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE } from "@/lib/api";

const TYPING_EXPIRY_MS = 3_000;
// FR-C206: 1s, 2s, 4s, 8s, 16s, capped at 30s - not a tight retry loop
// that hammers the backend (Non_Functional_Requirements.md's Reliability
// gate).
const RECONNECT_DELAYS_MS = [1_000, 2_000, 4_000, 8_000, 16_000, 30_000];

/**
 * FR-C203/FR-C206: opens WS /ws/support/tickets/{ticketId}, exposing
 * newly-arrived messages/typing events for a live thread, and reconnects
 * with exponential backoff on an unexpected drop. `connected` reports the
 * live state so a caller can fall back to "works, just not live" (manual
 * refresh) while it's false, rather than a hard error - the socket is
 * never the only source of truth either way (Rules.md): `onReconnect`
 * fires after a drop-then-reconnect specifically so the caller can
 * re-fetch the thread and catch anything that was missed while
 * disconnected, exactly the Reliability gate this FR exists to close.
 *
 * Auth travels as ?token= (a WS handshake can't carry an Authorization
 * header - docs/Rules.md), the same token everything else in this app reads
 * from localStorage, not a second auth mechanism.
 */
export function useSupportSocket(ticketId: string | null, onReconnect?: () => void) {
  const [connected, setConnected] = useState(false);
  const [messages, setMessages] = useState<any[]>([]);
  const [typingFrom, setTypingFrom] = useState<"staff" | "customer" | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const typingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onReconnectRef = useRef(onReconnect);
  onReconnectRef.current = onReconnect;

  useEffect(() => {
    setMessages([]);
    setTypingFrom(null);
    if (!ticketId) return;
    const token = localStorage.getItem("esim_token");
    if (!token) return;

    let stopped = false;
    let everConnected = false;
    let reconnectAttempt = 0;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    const wsBase = API_BASE.replace(/^http/, "ws");

    const connect = () => {
      const socket = new WebSocket(`${wsBase}/api/v1/ws/support/tickets/${ticketId}?token=${encodeURIComponent(token)}`);
      socketRef.current = socket;

      socket.onopen = () => {
        if (stopped) return;
        setConnected(true);
        if (everConnected) onReconnectRef.current?.();
        everConnected = true;
        reconnectAttempt = 0;
      };
      socket.onclose = (event) => {
        if (stopped) return;
        setConnected(false);
        // 4401/4403 (ws_support.py's WS_UNAUTHORIZED/WS_FORBIDDEN) is the
        // server deliberately rejecting this connection - the same token
        // would fail identically on every retry, so don't burn a backoff
        // cycle on something retrying can never fix.
        if (event.code === 4401 || event.code === 4403) return;
        const delay = RECONNECT_DELAYS_MS[Math.min(reconnectAttempt, RECONNECT_DELAYS_MS.length - 1)];
        reconnectAttempt += 1;
        reconnectTimer = setTimeout(connect, delay);
      };
      socket.onerror = () => setConnected(false);
      socket.onmessage = (event) => {
        let data: any;
        try {
          data = JSON.parse(event.data);
        } catch {
          return;
        }
        if (data?.type === "message" && data.message) {
          // A message this same tab just sent arrives back over its own
          // socket too (broadcast_to_ticket reaches every connection,
          // including the sender's) - dedupe by id so it doesn't render
          // twice next to the optimistic REST response.
          setMessages((prev) => (prev.some((m) => m.id === data.message.id) ? prev : [...prev, data.message]));
        } else if (data?.type === "typing") {
          setTypingFrom(data.from === "staff" ? "staff" : "customer");
          if (typingTimerRef.current) clearTimeout(typingTimerRef.current);
          // Clears within ~3s of the remote side stopping, even if no
          // explicit "stopped typing" event arrives (docs/Rules.md /
          // Non_Functional_Requirements.md).
          typingTimerRef.current = setTimeout(() => setTypingFrom(null), TYPING_EXPIRY_MS);
        }
      };
    };

    connect();

    return () => {
      stopped = true;
      if (typingTimerRef.current) clearTimeout(typingTimerRef.current);
      if (reconnectTimer) clearTimeout(reconnectTimer);
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, [ticketId]);

  const sendTyping = useCallback(() => {
    const socket = socketRef.current;
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "typing" }));
    }
  }, []);

  return { connected, messages, typingFrom, sendTyping };
}
