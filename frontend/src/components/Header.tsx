"use client";

import React, { useState, useEffect } from "react";
import Link from "next/link";
import { Globe, DollarSign, User, Shield, Briefcase, Wifi, Menu, X } from "lucide-react";
import { api, API_BASE } from "@/lib/api";
import { useAppSettings } from "@/lib/AppSettingsContext";

const CURRENCIES = ["USD", "BDT", "EUR", "GBP", "AED", "SAR"];

export default function Header() {
  const { lang, setLang, currency, setCurrency, languages, t } = useAppSettings();
  const [settings, setSettings] = useState<any>({ platform_name: "eSIM Global" });
  const [token, setToken] = useState<string | null>(null);
  const [userData, setUserData] = useState<any>(null);
  const [isMenuOpen, setIsMenuOpen] = useState(false);

  useEffect(() => {
    const savedToken = localStorage.getItem("esim_token");
    setToken(savedToken);

    api.getPublicSettings().then(setSettings).catch(console.error);
    if (savedToken) {
      api.getMe(savedToken).then(setUserData).catch(() => {
        localStorage.removeItem("esim_token");
        setToken(null);
      });
    }
  }, []);

  const activeLanguages = languages.filter((l) => l.is_active);

  return (
    <header className="sticky top-0 z-50 glass-panel border-b border-gray-200">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">

        {/* Brand Logo & Name */}
        <Link href="/" className="flex items-center space-x-3 group">
          {/* An uploaded logo already contains the brand name, so the text
              would render it twice - it's only a fallback for when no logo
              has been uploaded yet. */}
          {settings.logo_light ? (
            <img
              src={settings.logo_light.startsWith("http") ? settings.logo_light : `${API_BASE}${settings.logo_light}`}
              alt={settings.platform_name || "eSIM Global"}
              className="h-10 max-w-[180px] w-auto object-contain group-hover:scale-105 transition-transform"
            />
          ) : (
            <>
              <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-brand-600 to-accent-500 flex items-center justify-center shadow-md shadow-brand-600/20 group-hover:scale-105 transition-transform">
                <Wifi className="w-5 h-5 text-white" />
              </div>
              <span className="text-xl font-bold tracking-tight text-slate-900 group-hover:text-brand-600 transition-colors">
                {settings.platform_name || "eSIM Global"}
              </span>
            </>
          )}
        </Link>

        {/* Desktop Navigation */}
        <nav className="hidden md:flex items-center space-x-6 text-sm font-medium text-slate-600">
          <Link href="/" className="hover:text-slate-900 transition-colors">{t("nav", "countries", "Destinations")}</Link>
          <Link href="/my-esims" className="hover:text-slate-900 transition-colors">{t("common", "my_esims", "My eSIMs")}</Link>
          <Link href="/wallet" className="hover:text-slate-900 transition-colors">{t("common", "wallet", "Wallet")}</Link>
          {userData?.role === "SUPER_ADMIN" || userData?.role === "ADMIN" ? (
            <Link href="/admin" className="text-admin-600 hover:text-admin-700 flex items-center space-x-1">
              <Shield className="w-4 h-4" />
              <span>{t("common", "admin", "Admin Console")}</span>
            </Link>
          ) : null}
          {userData?.role === "MERCHANT" ? (
            <Link href="/reseller" className="text-merchant-600 hover:text-merchant-700 flex items-center space-x-1">
              <Briefcase className="w-4 h-4" />
              <span>{t("common", "merchant", "Partner Portal")}</span>
            </Link>
          ) : null}
        </nav>

        {/* Right Controls: Currency, Language & Auth */}
        <div className="hidden md:flex items-center space-x-3">

          {/* Currency Switcher */}
          <div className="relative">
            <select
              value={currency}
              onChange={(e) => setCurrency(e.target.value)}
              aria-label={t("nav", "currency", "Currency")}
              className="bg-white text-slate-700 text-xs font-semibold rounded-lg px-2.5 py-1.5 border border-gray-300 focus:outline-none focus:border-brand-500 cursor-pointer"
            >
              {CURRENCIES.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </div>

          {/* Language Switcher — populated from the Super Admin's active
              language list, not a hardcoded set, so a newly-activated
              language appears here immediately. */}
          <div className="relative">
            <select
              value={lang}
              onChange={(e) => setLang(e.target.value)}
              aria-label={t("nav", "language", "Language")}
              className="bg-white text-slate-700 text-xs font-semibold rounded-lg px-2.5 py-1.5 border border-gray-300 focus:outline-none focus:border-brand-500 cursor-pointer"
            >
              {(activeLanguages.length ? activeLanguages : [{ code: "en", native_name: "English", flag_emoji: "🇺🇸" }]).map((l) => (
                <option key={l.code} value={l.code}>{l.flag_emoji} {l.native_name}</option>
              ))}
            </select>
          </div>

          {/* User Account / Auth */}
          {token && userData ? (
            <Link href="/profile" className="flex items-center space-x-2 bg-gray-50 hover:bg-gray-100 px-3 py-1.5 rounded-lg border border-gray-200 text-xs font-medium text-slate-900 transition-colors">
              <User className="w-3.5 h-3.5 text-brand-600" />
              <span>{userData.username}</span>
              <span className="text-emerald-600 font-mono">
                ${userData.wallets?.[0]?.balance?.toFixed(2) || "0.00"}
              </span>
            </Link>
          ) : (
            <Link
              href="/auth/login"
              className="bg-brand-600 hover:bg-brand-500 text-white text-xs font-semibold px-4 py-2 rounded-lg shadow-md shadow-brand-600/20 transition-all hover:scale-105"
            >
              {t("common", "login", "Sign In")}
            </Link>
          )}

        </div>

        {/* Mobile menu button */}
        <div className="md:hidden flex items-center space-x-2">
          <select
            value={currency}
            onChange={(e) => setCurrency(e.target.value)}
            aria-label={t("nav", "currency", "Currency")}
            className="bg-white text-xs font-bold rounded px-1.5 py-1 text-slate-700 border border-gray-300"
          >
            {CURRENCIES.map((c) => (<option key={c} value={c}>{c}</option>))}
          </select>
          <button
            onClick={() => setIsMenuOpen(!isMenuOpen)}
            aria-label={isMenuOpen ? "Close menu" : "Open menu"}
            className="p-2 text-slate-500 hover:text-slate-900"
          >
            {isMenuOpen ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
          </button>
        </div>

      </div>

      {/* Mobile Dropdown */}
      {isMenuOpen && (
        <div className="md:hidden px-4 pt-2 pb-4 space-y-2 bg-white border-b border-gray-200">
          <Link href="/" onClick={() => setIsMenuOpen(false)} className="block py-2 text-slate-600">{t("nav", "countries", "Destinations")}</Link>
          <Link href="/my-esims" onClick={() => setIsMenuOpen(false)} className="block py-2 text-slate-600">{t("common", "my_esims", "My eSIMs")}</Link>
          <Link href="/wallet" onClick={() => setIsMenuOpen(false)} className="block py-2 text-slate-600">{t("common", "wallet", "Wallet")}</Link>
          {userData?.role === "SUPER_ADMIN" || userData?.role === "ADMIN" ? (
            <Link href="/admin" onClick={() => setIsMenuOpen(false)} className="block py-2 text-admin-600">{t("common", "admin", "Admin Console")}</Link>
          ) : null}
          <div className="pt-2 border-t border-gray-200">
            {token ? (
              <Link href="/profile" onClick={() => setIsMenuOpen(false)} className="block py-2 text-emerald-600">
                {t("common", "profile", "Account")} ({userData?.username})
              </Link>
            ) : (
              <Link href="/auth/login" onClick={() => setIsMenuOpen(false)} className="block py-2 text-brand-600 font-bold">
                {t("common", "login", "Sign In")} / {t("common", "register", "Register")}
              </Link>
            )}
          </div>
        </div>
      )}
    </header>
  );
}
