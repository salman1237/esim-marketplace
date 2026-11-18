"use client";

import TicketListAndCompose from "@/components/support/TicketListAndCompose";

// FR-C202: this page's own ticket-list/new-ticket logic now lives in
// TicketListAndCompose, shared with ChatWidget's slide-over panel - never a
// second, divergent implementation.
export default function SupportPage() {
  return <TicketListAndCompose />;
}
