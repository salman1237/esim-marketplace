"use client";

import React, { createContext, useContext, useEffect, useState, useCallback } from "react";
import { api } from "./api";

interface LanguageMeta {
  code: string;
  name: string;
  native_name: string;
  flag_emoji?: string;
  is_active: boolean;
  is_rtl: boolean;
}

interface AppSettingsContextValue {
  lang: string;
  setLang: (lang: string) => void;
  currency: string;
  setCurrency: (currency: string) => void;
  isRTL: boolean;
  languages: LanguageMeta[];
  t: (namespace: string, key: string, fallback?: string) => string;
  convert: (amountUsd: number) => number;
  convertTo: (amountUsd: number, targetCurrency: string) => number;
  formatPrice: (amountUsd: number) => string;
  maintenanceMode: boolean;
  platformName: string;
}

const AppSettingsContext = createContext<AppSettingsContextValue | null>(null);

// Symbols for currencies the currency switcher and admin override form
// offer; anything else falls back to a "CODE " prefix.
const CURRENCY_SYMBOLS: Record<string, string> = {
  USD: "$", BDT: "৳", EUR: "€", GBP: "£", AED: "د.إ", SAR: "﷼", THB: "฿", SGD: "S$", JPY: "¥", MYR: "RM", INR: "₹",
};

const ZERO_DECIMAL_CURRENCIES = new Set(["JPY"]);

export function AppSettingsProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLangState] = useState("en");
  const [currency, setCurrencyState] = useState("USD");
  const [languages, setLanguages] = useState<LanguageMeta[]>([]);
  const [translations, setTranslations] = useState<Record<string, Record<string, string>>>({});
  const [rates, setRates] = useState<Record<string, number>>({ USD: 1 });
  const [maintenanceMode, setMaintenanceMode] = useState(false);
  const [platformName, setPlatformName] = useState("eSIM Global");

  useEffect(() => {
    try {
      const savedLang = localStorage.getItem("esim_lang");
      const savedCurrency = localStorage.getItem("esim_currency");
      if (savedLang) setLangState(savedLang);
      if (savedCurrency) setCurrencyState(savedCurrency);
    } catch {
      // localStorage unavailable (private browsing, etc.) — defaults stand.
    }
  }, []);

  useEffect(() => {
    api.getLanguages().then(setLanguages).catch(() => {});
  }, []);

  useEffect(() => {
    api.getPublicSettings().then((s: any) => {
      setMaintenanceMode(!!s.maintenance_mode);
      if (s.platform_name) setPlatformName(s.platform_name);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    api.getRates().then((rows: any[]) => {
      const map: Record<string, number> = { USD: 1 };
      for (const r of rows) {
        const rate = r.is_manual_override && r.manual_rate ? parseFloat(r.manual_rate) : parseFloat(r.rate_to_base);
        if (!Number.isNaN(rate)) map[r.currency_code] = rate;
      }
      setRates(map);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    api.getTranslations(lang).then((data: any) => setTranslations(data.namespaces || {})).catch(() => {});
  }, [lang]);

  const setLang = useCallback((code: string) => {
    setLangState(code);
    try { localStorage.setItem("esim_lang", code); } catch {}
  }, []);

  const setCurrency = useCallback((code: string) => {
    setCurrencyState(code);
    try { localStorage.setItem("esim_currency", code); } catch {}
  }, []);

  const t = useCallback(
    (namespace: string, key: string, fallback?: string) => translations[namespace]?.[key] ?? fallback ?? key,
    [translations]
  );

  const convertTo = useCallback((amountUsd: number, targetCurrency: string) => amountUsd * (rates[targetCurrency] ?? 1), [rates]);
  const convert = useCallback((amountUsd: number) => convertTo(amountUsd, currency), [convertTo, currency]);

  const formatPrice = useCallback((amountUsd: number) => {
    const converted = convert(amountUsd);
    const symbol = CURRENCY_SYMBOLS[currency] ?? `${currency} `;
    const decimals = ZERO_DECIMAL_CURRENCIES.has(currency) ? 0 : 2;
    return `${symbol}${converted.toFixed(decimals)}`;
  }, [convert, currency]);

  const activeLang = languages.find((l) => l.code === lang);
  const isRTL = activeLang ? activeLang.is_rtl : lang === "ar";

  useEffect(() => {
    document.documentElement.lang = lang;
    document.documentElement.dir = isRTL ? "rtl" : "ltr";
  }, [lang, isRTL]);

  return (
    <AppSettingsContext.Provider value={{ lang, setLang, currency, setCurrency, isRTL, languages, t, convert, convertTo, formatPrice, maintenanceMode, platformName }}>
      {children}
    </AppSettingsContext.Provider>
  );
}

export function useAppSettings() {
  const ctx = useContext(AppSettingsContext);
  if (!ctx) throw new Error("useAppSettings must be used within an AppSettingsProvider");
  return ctx;
}
