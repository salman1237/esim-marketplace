"use client";

import React, { useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { MessageCircle, X } from "lucide-react";
import { api } from "@/lib/api";
import TicketListAndCompose from "@/components/support/TicketListAndCompose";

const UNREAD_POLL_MS = 30_000;

// FR-C201: global, every page except auth pages (docs/Functional_Requirements.md).
// Logged in/out state and the login-redirect pattern mirror Header.tsx and
// PackageBrowser.tsx's own "next=" convention - not a second implementation.
function isAuthPage(pathname: string | null): boolean {
  return !!pathname && pathname.startsWith("/auth");
}

function useFocusTrap(containerRef: React.RefObject<HTMLElement | null>, active: boolean) {
  useEffect(() => {
    if (!active) return;
    const container = containerRef.current;
    if (!container) return;

    const selector = 'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])';
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== "Tab") return;
      const focusable = Array.from(container.querySelectorAll<HTMLElement>(selector));
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    container.addEventListener("keydown", onKeyDown);
    return () => container.removeEventListener("keydown", onKeyDown);
  }, [active, containerRef]);
}

export default function ChatWidget() {
  const pathname = usePathname();
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [slideIn, setSlideIn] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);
  const panelRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    setToken(localStorage.getItem("esim_token"));
  }, []);

  // Status "ANSWERED" means support just replied and it's waiting on the
  // customer (support_svc.post_message) - the same proxy for "unread" a
  // customer would read from the ticket list themselves, not a new concept.
  useEffect(() => {
    if (!token) {
      setUnreadCount(0);
      return;
    }
    let cancelled = false;
    const refresh = async () => {
      try {
        const tickets = await api.getMyTickets(token);
        if (!cancelled) setUnreadCount(tickets.filter((t: any) => t.status === "ANSWERED").length);
      } catch {
        // Transient failure - keep showing the last known count rather than
        // flashing it to zero.
      }
    };
    refresh();
    const interval = setInterval(refresh, UNREAD_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [token]);

  useEffect(() => {
    if (!open) {
      setSlideIn(false);
      return;
    }
    closeButtonRef.current?.focus();
    // Mount off-screen first, then transition in on the next frame - a
    // plain Tailwind setup (no tailwindcss-animate plugin here) rather than
    // an animate-in utility class that doesn't exist in this build.
    const frame = requestAnimationFrame(() => setSlideIn(true));
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  useFocusTrap(panelRef, open);

  if (isAuthPage(pathname)) return null;

  const handleButtonClick = () => {
    if (!token) {
      // Confirmed: POST /support/tickets requires get_current_user - a
      // ticket cannot be opened signed out (docs/Architecture.md). Same
      // next= redirect convention PackageBrowser.tsx already uses, not a
      // new mechanism.
      const here = typeof window !== "undefined" ? window.location.pathname + window.location.search : "/";
      window.location.href = `/auth/login?next=${encodeURIComponent(here)}`;
      return;
    }
    setOpen((v) => !v);
  };

  return (
    <>
      <button
        type="button"
        onClick={handleButtonClick}
        aria-label={open ? "Close support chat" : "Chat with support"}
        aria-expanded={open}
        className="fixed z-[70] right-4 md:right-6 bottom-20 md:bottom-6 w-14 h-14 rounded-full bg-brand-600 hover:bg-brand-500 text-white shadow-2xl flex items-center justify-center transition-colors print:hidden"
      >
        {open ? <X className="w-6 h-6" /> : <MessageCircle className="w-6 h-6" />}
        {!open && unreadCount > 0 && (
          <span
            className="absolute -top-1 -right-1 min-w-[20px] h-5 px-1 rounded-full bg-rose-600 text-white text-[11px] font-bold flex items-center justify-center border-2 border-white"
            aria-hidden="true"
          >
            {unreadCount > 9 ? "9+" : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div className="fixed inset-0 z-[65] print:hidden">
          <div className="absolute inset-0 bg-slate-900/40" onClick={() => setOpen(false)} aria-hidden="true" />
          <div
            ref={panelRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="chat-widget-title"
            className={`absolute right-0 top-0 h-full w-full sm:w-[400px] bg-white shadow-2xl flex flex-col transition-transform duration-300 ease-out ${
              slideIn ? "translate-x-0" : "translate-x-full"
            }`}
          >
            <div className="flex items-center justify-between px-4 h-14 border-b border-gray-200 shrink-0">
              <h2 id="chat-widget-title" className="text-sm font-bold text-slate-900">Support</h2>
              <button
                ref={closeButtonRef}
                type="button"
                onClick={() => setOpen(false)}
                aria-label="Close"
                className="p-1.5 rounded-lg hover:bg-gray-100 text-slate-500"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-4">
              {/* FR-C202: same ticket-list/new-ticket logic as /support,
                  never a second implementation. FR-C203 will swap
                  onOpenTicket to switch this panel to an in-place live
                  thread instead of leaving it. */}
              <TicketListAndCompose
                compact
                onOpenTicket={(ticketId) => {
                  setOpen(false);
                  router.push(`/support/${ticketId}`);
                }}
              />
            </div>
          </div>
        </div>
      )}
    </>
  );
}
