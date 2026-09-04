import type { Metadata, Viewport } from "next";
import "./globals.css";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import MobileBottomNav from "@/components/MobileBottomNav";
import MaintenanceGate from "@/components/MaintenanceGate";
import { AppSettingsProvider } from "@/lib/AppSettingsContext";
import { API_BASE } from "@/lib/api";

const DEFAULT_TITLE = "eSIM Global — High-Speed Data in 200+ Countries";
const DEFAULT_DESCRIPTION = "Instant high-speed international eSIM mobile data. QR code delivery in seconds. No roaming fees.";

// A real per-request fetch (not the static `metadata` export) so Super
// Admin changes to SEO title/description/OG image reach page metadata
// without a rebuild, per the plan's "instantly reflected... without
// rebuilding or redeploying" requirement. revalidate keeps this from
// hitting the settings API on literally every request while still
// picking up changes within a few minutes.
export async function generateMetadata(): Promise<Metadata> {
  try {
    const res = await fetch(`${API_BASE}/api/v1/settings/public`, { next: { revalidate: 300 } });
    if (!res.ok) throw new Error(`settings fetch failed: ${res.status}`);
    const settings = await res.json();
    const title = settings.seo_title || settings.platform_name || DEFAULT_TITLE;
    const description = settings.seo_description || settings.tagline_en || DEFAULT_DESCRIPTION;
    const ogImageUrl = settings.og_image
      ? (settings.og_image.startsWith("http") ? settings.og_image : `${API_BASE}${settings.og_image}`)
      : undefined;

    return {
      title,
      description,
      openGraph: { title, description, images: ogImageUrl ? [ogImageUrl] : undefined },
    };
  } catch {
    // Settings API unreachable at build/request time — a real default,
    // not an empty page title.
    return { title: DEFAULT_TITLE, description: DEFAULT_DESCRIPTION };
  }
}

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 5,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" dir="ltr">
      <body className="min-h-screen flex flex-col bg-slate-950 text-slate-100 antialiased selection:bg-brand-500 selection:text-white pb-16 md:pb-0">
        <AppSettingsProvider>
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
