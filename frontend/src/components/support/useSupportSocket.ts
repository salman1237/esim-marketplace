"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE } from "@/lib/api";

const TYPING_EXPIRY_MS = 3_000;

/**
 * FR-C203: opens WS /ws/support/tickets/{ticketId}, exposing newly-arrived
 * messages/typing events for a live thread. Reconnect-with-backoff and the
 * manual-refresh fallback are FR-C206's own scope - this hook connects once
 * and reports `connected`, it does not retry on its own yet.
 *
 * Auth travels as ?token= (a WS handshake can't carry an Authorization
 * header - docs/Rules.md), the same token everything else in this app reads
 * from localStorage, not a second auth mechanism.
 */
export function useSupportSocket(ticketId: string | null) {
  const [connected, setConnected] = useState(false);
  const [messages, setMessages] = useState<any[]>([]);
  const [typingFrom, setTypingFrom] = useState<"staff" | "customer" | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const typingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    setMessages([]);
    setTypingFrom(null);
    if (!ticketId) return;
    const token = localStorage.getItem("esim_token");
    if (!token) return;

    const wsBase = API_BASE.replace(/^http/, "ws");
    const socket = new WebSocket(`${wsBase}/api/v1/ws/support/tickets/${ticketId}?token=${encodeURIComponent(token)}`);
    socketRef.current = socket;

    socket.onopen = () => setConnected(true);
    socket.onclose = () => setConnected(false);
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

    return () => {
      if (typingTimerRef.current) clearTimeout(typingTimerRef.current);
      socket.close();
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
