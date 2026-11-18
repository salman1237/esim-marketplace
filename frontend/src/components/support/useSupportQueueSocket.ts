"use client";

import { useEffect, useRef, useState } from "react";
import { API_BASE } from "@/lib/api";

// Same backoff shape as useSupportSocket (FR-C206) - a separate small hook
// rather than sharing its internals, since the queue channel's payload and
// lifecycle (enabled by a staff role, not a ticketId) are genuinely
// different, not just a style variation of the same thing.
const RECONNECT_DELAYS_MS = [1_000, 2_000, 4_000, 8_000, 16_000, 30_000];

/**
 * FR-C301: subscribes to WS /ws/support/queue (staff-only -
 * ws_support.py's queue_socket). Fires `onUpdate` on every `ticket_updated`
 * event rather than trying to patch one row from the event's own
 * lightweight summary - the existing GET /support/queue call
 * (SupportTab.tsx's own `load()`) is the real source of truth for filters/
 * search/counts together, so a full re-fetch is correct here, not a
 * shortcut.
 */
export function useSupportQueueSocket(enabled: boolean, onUpdate: () => void) {
  const [connected, setConnected] = useState(false);
  const onUpdateRef = useRef(onUpdate);
  onUpdateRef.current = onUpdate;

  useEffect(() => {
    if (!enabled) return;
    const token = localStorage.getItem("esim_token");
    if (!token) return;

    let stopped = false;
    let reconnectAttempt = 0;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let socket: WebSocket | null = null;
    const wsBase = API_BASE.replace(/^http/, "ws");

    const connect = () => {
      socket = new WebSocket(`${wsBase}/api/v1/ws/support/queue?token=${encodeURIComponent(token)}`);
      socket.onopen = () => {
        if (stopped) return;
        setConnected(true);
        reconnectAttempt = 0;
      };
      socket.onclose = (event) => {
        if (stopped) return;
        setConnected(false);
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
        if (data?.type === "ticket_updated") onUpdateRef.current();
      };
    };

    connect();

    return () => {
      stopped = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, [enabled]);

  return { connected };
}
