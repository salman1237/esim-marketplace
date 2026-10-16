"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Briefcase, Compass, Handshake, QrCode, Wallet, User } from "lucide-react";
import { useAppSettings } from "@/lib/AppSettingsContext";
import { portalsFor } from "@/lib/portals";

export default function MobileBottomNav() {
  const pathname = usePathname();
  const { t, me } = useAppSettings();
  const portals = portalsFor(me);

  const tabs = [
    { href: "/destinations", label: t("common", "explore", "Explore"), icon: Compass },
    { href: "/my-esims", label: t("common", "my_esims", "My eSIMs"), icon: QrCode },
    { href: "/wallet", label: t("common", "wallet", "Wallet"), icon: Wallet },
    // Both can be present: an agent who also sells keeps role=MERCHANT, so
    // these are independent checks rather than a chain. Placed before Profile
    // so the row stays in the same order whether one, both, or neither apply.
    ...(portals.isAgent ? [{ href: "/agent", label: "Agent", icon: Handshake }] : []),
    ...(portals.isPartner ? [{ href: "/reseller", label: "Partner", icon: Briefcase }] : []),
    { href: "/profile", label: t("common", "profile", "Profile"), icon: User },
  ];

  return (
    <nav className="md:hidden fixed bottom-0 left-0 right-0 z-50 glass-panel border-t border-gray-200 h-16 flex items-center justify-around px-1 print:hidden">
      {tabs.map((tab) => {
        const Icon = tab.icon;
        const isActive = pathname === tab.href;
        // The portal tabs push this to six items on a 390px screen, so each
        // one has to be allowed to shrink rather than overflow the row.
        const tone = isActive
          ? tab.href === "/reseller"
            ? "text-merchant-600 font-semibold"
            : "text-brand-600 font-semibold"
          : "text-slate-500 hover:text-slate-700";
        return (
          <Link
            key={tab.href}
            href={tab.href}
            className={`flex flex-col items-center justify-center flex-1 min-w-0 h-full min-h-[44px] px-0.5 transition-colors ${tone}`}
          >
            <Icon className={`w-5 h-5 mb-1 shrink-0 ${isActive ? "scale-110" : ""}`} />
            <span className="text-[10px] tracking-tight leading-none w-full text-center truncate">{tab.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
