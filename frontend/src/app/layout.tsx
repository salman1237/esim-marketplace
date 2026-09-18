import type { Metadata, Viewport } from "next";
import "./globals.css";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import MobileBottomNav from "@/components/MobileBottomNav";
import MaintenanceGate from "@/components/MaintenanceGate";
import { AppSettingsProvider } from "@/lib/AppSettingsContext";
import { API_BASE } from "@/lib/api";

const DEFAULT_TITLE = "High-Speed eSIM Data in 200+ Countries";
const DEFAULT_DESCRIPTION = "Instant high-speed international eSIM mobile data. QR code delivery in seconds. No roaming fees.";

// A real fetch (not the static `metadata` export) so Super Admin changes to
// branding and SEO reach pages without a rebuild. revalidate keeps this from
// hitting the settings API on every request while still picking up changes
// within a few minutes. Next dedupes the identical fetch between
// generateMetadata and the layout within a render.
async function fetchPublicSettings(): Promise<any | null> {
  try {
    const res = await fetch(`${API_BASE}/api/v1/settings/public`, { next: { revalidate: 300 } });
    if (!res.ok) throw new Error(`settings fetch failed: ${res.status}`);
    return await res.json();
  } catch {
    return null;
  }
}

export async function generateMetadata(): Promise<Metadata> {
  const settings = await fetchPublicSettings();
  if (!settings) {
    // Settings API unreachable at build/request time — a real default,
    // not an empty page title.
    return { title: DEFAULT_TITLE, description: DEFAULT_DESCRIPTION };
  }
  const title = settings.seo_title || (settings.platform_name ? `${settings.platform_name} — ${DEFAULT_TITLE}` : DEFAULT_TITLE);
  const description = settings.seo_description || settings.tagline_en || DEFAULT_DESCRIPTION;
  const ogImageUrl = settings.og_image
    ? (settings.og_image.startsWith("http") ? settings.og_image : `${API_BASE}${settings.og_image}`)
    : undefined;

  return {
    title,
    description,
    openGraph: { title, description, images: ogImageUrl ? [ogImageUrl] : undefined },
  };
}

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 5,
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  // Rendered into the HTML so the header/footer show the real logo on first
  // paint instead of a placeholder that flashes until the browser fetches it.
  const initialSettings = await fetchPublicSettings();

  return (
    <html lang="en" dir="ltr">
      <body className="min-h-screen flex flex-col bg-gray-50 text-slate-900 antialiased selection:bg-brand-500 selection:text-white pb-16 md:pb-0 print:bg-white print:pb-0 print:min-h-0">
        <AppSettingsProvider initialSettings={initialSettings}>
          <MaintenanceGate>
            <Header />
            <main className="flex-1">
              {children}
            </main>
            <Footer />
            <MobileBottomNav />
          </MaintenanceGate>
        </AppSettingsProvider>
      </body>
    </html>
  );
}
