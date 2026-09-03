import type { Metadata, Viewport } from "next";
import "./globals.css";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import MobileBottomNav from "@/components/MobileBottomNav";
import MaintenanceGate from "@/components/MaintenanceGate";
import { AppSettingsProvider } from "@/lib/AppSettingsContext";

export const metadata: Metadata = {
  title: "eSIM Global — High-Speed Data in 200+ Countries",
  description: "Instant high-speed international eSIM mobile data. QR code delivery in seconds. No roaming fees.",
};

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
