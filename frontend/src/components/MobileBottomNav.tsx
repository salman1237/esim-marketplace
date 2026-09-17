"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Compass, QrCode, Wallet, User } from "lucide-react";
import { useAppSettings } from "@/lib/AppSettingsContext";

export default function MobileBottomNav() {
  const pathname = usePathname();
  const { t } = useAppSettings();

  const tabs = [
    { href: "/destinations", label: t("common", "explore", "Explore"), icon: Compass },
    { href: "/my-esims", label: t("common", "my_esims", "My eSIMs"), icon: QrCode },
    { href: "/wallet", label: t("common", "wallet", "Wallet"), icon: Wallet },
    { href: "/profile", label: t("common", "profile", "Profile"), icon: User },
  ];

  return (
    <nav className="md:hidden fixed bottom-0 left-0 right-0 z-50 glass-panel border-t border-gray-200 h-16 flex items-center justify-around px-2">
      {tabs.map((tab) => {
        const Icon = tab.icon;
        const isActive = pathname === tab.href;
        return (
          <Link
            key={tab.href}
            href={tab.href}
            className={`flex flex-col items-center justify-center flex-1 h-full min-h-[44px] transition-colors ${
              isActive ? "text-brand-600 font-semibold" : "text-slate-500 hover:text-slate-700"
            }`}
          >
            <Icon className={`w-5 h-5 mb-1 ${isActive ? "scale-110" : ""}`} />
            <span className="text-[10px] tracking-tight">{tab.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
