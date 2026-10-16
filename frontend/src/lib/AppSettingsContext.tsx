"use client";

import React, { createContext, useContext, useEffect, useState, useCallback } from "react";
import { api, API_BASE } from "./api";

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
  // GET /settings/public. Server-rendered into the first paint by the root
  // layout, then refreshed client-side. null only if both fetches failed.
  publicSettings: any | null;
  // The signed-in account, already fetched here for its currency preference.
  // Shared so the bottom navigation can tell an agent from a partner without
  // a second identical request on every page.
  me: any | null;
}

const AppSettingsContext = createContext<AppSettingsContextValue | null>(null);

// Symbols for currencies the currency switcher and admin override form
// offer; anything else falls back to a "CODE " prefix.
const CURRENCY_SYMBOLS: Record<string, string> = {
  USD: "$", BDT: "৳", EUR: "€", GBP: "£", AED: "د.إ", SAR: "﷼", THB: "฿", SGD: "S$", JPY: "¥", MYR: "RM", INR: "₹",
};

const ZERO_DECIMAL_CURRENCIES = new Set(["JPY"]);

// What someone sees before they have told us anything. Overridable at build
// time, because a deployment aimed at a different market would want its own.
export const DEFAULT_DISPLAY_CURRENCY = process.env.NEXT_PUBLIC_DEFAULT_CURRENCY || "BDT";

export function AppSettingsProvider({ children, initialSettings }: { children: React.ReactNode; initialSettings?: any | null }) {
  const [lang, setLangState] = useState("en");
  // The platform's books are kept in EUR - that is the base every rate is
  // quoted against and every amount is stored in. What a visitor SEES is a
  // different question, and the answer is taka: the home market does not
  // think in euros, and making them convert in their head to find out what a
  // package costs loses the sale before the package page finishes loading.
  // A signed-in account's own preference overrides this a moment later.
  const [currency, setCurrencyState] = useState(DEFAULT_DISPLAY_CURRENCY);
  const [languages, setLanguages] = useState<LanguageMeta[]>([]);
  const [translations, setTranslations] = useState<Record<string, Record<string, string>>>({});
  const [rates, setRates] = useState<Record<string, number>>({ EUR: 1 });
  // Seeded from the server so the real brand is in the first paint - a
  // hardcoded placeholder name here flashed on every page load until the
  // client-side fetch replaced it.
  const [publicSettings, setPublicSettings] = useState<any | null>(initialSettings ?? null);
  const [me, setMe] = useState<any | null>(null);
  const maintenanceMode = !!publicSettings?.maintenance_mode;
  const platformName: string = publicSettings?.platform_name || "";

  useEffect(() => {
    try {
      const savedLang = localStorage.getItem("esim_lang");
      const savedCurrency = localStorage.getItem("esim_currency_v2");
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
      setPublicSettings(s);
      if (s.favicon) {
        let link = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
        if (!link) {
          link = document.createElement("link");
          link.rel = "icon";
          document.head.appendChild(link);
        }
        link.href = s.favicon.startsWith("http") ? s.favicon : `${API_BASE}${s.favicon}`;
      }
    }).catch(() => {});
  }, []);

  useEffect(() => {
    api.getRates().then((rows: any[]) => {
      const map: Record<string, number> = { EUR: 1 };
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

  // A signed-in account's currency follows them across devices, which browser
  // storage alone never did - and the wallet's top-up box reads it to decide
  // what the customer is typing in.
  useEffect(() => {
    let token: string | null = null;
    try { token = localStorage.getItem("esim_token"); } catch { return; }
    if (!token) return;
    api.getMe(token)
      .then((me: any) => {
        setMe(me);
        if (me?.preferred_currency) {
          setCurrencyState(me.preferred_currency);
          try { localStorage.setItem("esim_currency_v2", me.preferred_currency); } catch {}
        }
      })
      .catch(() => {});
  }, []);

  const setCurrency = useCallback((code: string) => {
    setCurrencyState(code);
    try { localStorage.setItem("esim_currency_v2", code); } catch {}
    try {
      const token = localStorage.getItem("esim_token");
      // Best-effort: the switch has already taken effect locally, so a failed
      // save must not undo it or interrupt the customer.
      if (token) api.updateMyPreferences(token, code).catch(() => {});
    } catch {}
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
    <AppSettingsContext.Provider value={{ lang, setLang, currency, setCurrency, isRTL, languages, t, convert, convertTo, formatPrice, maintenanceMode, platformName, publicSettings, me }}>
      {children}
    </AppSettingsContext.Provider>
  );
}

export function useAppSettings() {
  const ctx = useContext(AppSettingsContext);
  if (!ctx) throw new Error("useAppSettings must be used within an AppSettingsProvider");
  return ctx;
}
