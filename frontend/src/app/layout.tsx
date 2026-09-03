"use client";

import React, { useEffect } from "react";
import "./globals.css";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import MobileBottomNav from "@/components/MobileBottomNav";
import { AppSettingsProvider, useAppSettings } from "@/lib/AppSettingsContext";

function HtmlAttributesSync() {
  const { lang, isRTL } = useAppSettings();
  useEffect(() => {
    document.documentElement.lang = lang;
    document.documentElement.dir = isRTL ? "rtl" : "ltr";
  }, [lang, isRTL]);
  return null;
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" dir="ltr">
      <head>
        <title>eSIM Global — High-Speed Data in 200+ Countries</title>
        <meta name="description" content="Instant high-speed international eSIM mobile data. QR code delivery in seconds. No roaming fees." />
        <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=5" />
      </head>
      <body className="min-h-screen flex flex-col bg-slate-950 text-slate-100 antialiased selection:bg-brand-500 selection:text-white pb-16 md:pb-0">
        <AppSettingsProvider>
          <HtmlAttributesSync />
          <Header />
          <main className="flex-1">
            {children}
          </main>
          <Footer />
          <MobileBottomNav />
        </AppSettingsProvider>
      </body>
    </html>
  );
}
