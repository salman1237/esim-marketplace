import { API_BASE } from "@/lib/api";

export type Destination = { country: any; products: any[] };

// Shared by /explore/[slug] and /explore/[slug]/[productId] - server-side
// fetch so both pages render with real data for link previews (WhatsApp,
// Messenger, etc.) and SEO, not a client-only fetch.
export async function fetchDestination(slug: string): Promise<Destination | null> {
  try {
    const res = await fetch(`${API_BASE}/api/v1/catalog/destinations/${encodeURIComponent(slug)}`, {
      next: { revalidate: 300 },
    });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}
