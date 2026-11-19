/**
 * Guest (non-logged-in) support chat identity - FR-C402/C406
 * (docs/Architecture.md "Guest chat"). A bare guest_token minted by
 * POST /support/guest/session, kept only in localStorage - never a cookie
 * session, never server-renewed. "Active guest ticket" is the one ticket
 * the widget shows for a guest in this browser (guests don't get a ticket
 * LIST view - there is no such endpoint, and one open conversation is the
 * whole guest use case: ask something before signing up).
 */
import { api } from "@/lib/api";

const TOKEN_KEY = "esim_guest_token";
const TICKET_KEY = "esim_guest_ticket_id";

export function getStoredGuestToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export async function getOrCreateGuestToken(): Promise<string> {
  const existing = getStoredGuestToken();
  if (existing) return existing;
  const { guest_token } = await api.createGuestSession();
  localStorage.setItem(TOKEN_KEY, guest_token);
  return guest_token;
}

export function getActiveGuestTicketId(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TICKET_KEY);
}

export function setActiveGuestTicketId(ticketId: string): void {
  localStorage.setItem(TICKET_KEY, ticketId);
}

/** FR-C405/C407: called right after a successful login/register. A no-op
 * if this browser never opened a guest ticket. Clears local guest state
 * either way afterward - a claimed token no longer owns anything server-
 * side (Rules.md), so there's nothing left to keep pointing at it. */
export async function claimGuestTicketsIfAny(token: string): Promise<void> {
  const guestToken = getStoredGuestToken();
  if (!guestToken) return;
  try {
    await api.claimGuestTickets(token, guestToken);
  } finally {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(TICKET_KEY);
  }
}
