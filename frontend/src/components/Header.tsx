"use client";

import React, { useState, useEffect } from "react";
import Link from "next/link";
import { Globe, DollarSign, User, Shield, Briefcase, Wifi, Menu, X } from "lucide-react";
import { api } from "@/lib/api";

interface HeaderProps {
  currentLang: string;
  setLang: (lang: string) => void;
  currentCurrency: string;
  setCurrency: (currency: string) => void;
}

export default function Header({ currentLang, setLang, currentCurrency, setCurrency }: HeaderProps) {
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

  const currencies = ["USD", "BDT", "EUR", "GBP", "AED", "SAR"];
  const languages = [
    { code: "en", name: "English", flag: "🇺🇸" },
    { code: "bn", name: "বাংলা", flag: "🇧🇩" },
    { code: "ar", name: "العربية", flag: "🇸🇦", rtl: true },
    { code: "es", name: "Español", flag: "🇪🇸" },
  ];

  return (
    <header className="sticky top-0 z-50 glass-panel border-b border-white/10">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        
        {/* Brand Logo & Name */}
        <Link href="/" className="flex items-center space-x-3 group">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-brand-600 to-accent-500 flex items-center justify-center shadow-lg shadow-brand-600/30 group-hover:scale-105 transition-transform">
            <Wifi className="w-5 h-5 text-white" />
          </div>
          <span className="text-xl font-bold tracking-tight text-white group-hover:text-brand-300 transition-colors">
            {settings.platform_name || "eSIM Global"}
          </span>
        </Link>

        {/* Desktop Navigation */}
        <nav className="hidden md:flex items-center space-x-6 text-sm font-medium text-slate-300">
          <Link href="/" className="hover:text-white transition-colors">Destinations</Link>
          <Link href="/my-esims" className="hover:text-white transition-colors">My eSIMs</Link>
          <Link href="/wallet" className="hover:text-white transition-colors">Wallet</Link>
          {userData?.role === "SUPER_ADMIN" || userData?.role === "ADMIN" ? (
            <Link href="/admin" className="text-brand-400 hover:text-brand-300 flex items-center space-x-1">
              <Shield className="w-4 h-4" />
              <span>Admin Console</span>
            </Link>
          ) : null}
          {userData?.role === "MERCHANT" ? (
            <Link href="/reseller" className="text-merchant-500 hover:text-merchant-400 flex items-center space-x-1">
              <Briefcase className="w-4 h-4" />
              <span>Partner Portal</span>
            </Link>
          ) : null}
        </nav>

        {/* Right Controls: Currency, Language & Auth */}
        <div className="hidden md:flex items-center space-x-3">
          
          {/* Currency Switcher */}
          <div className="relative">
            <select
              value={currentCurrency}
              onChange={(e) => setCurrency(e.target.value)}
              className="bg-slate-800 text-slate-200 text-xs font-semibold rounded-lg px-2.5 py-1.5 border border-slate-700 focus:outline-none focus:border-brand-500 cursor-pointer"
            >
              {currencies.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </div>

          {/* Language Switcher */}
          <div className="relative">
            <select
              value={currentLang}
              onChange={(e) => setLang(e.target.value)}
              className="bg-slate-800 text-slate-200 text-xs font-semibold rounded-lg px-2.5 py-1.5 border border-slate-700 focus:outline-none focus:border-brand-500 cursor-pointer"
            >
              {languages.map((l) => (
                <option key={l.code} value={l.code}>{l.flag} {l.name}</option>
              ))}
            </select>
          </div>

          {/* User Account / Auth */}
          {token && userData ? (
            <Link href="/profile" className="flex items-center space-x-2 bg-slate-800 hover:bg-slate-700 px-3 py-1.5 rounded-lg border border-slate-700 text-xs font-medium text-white transition-colors">
              <User className="w-3.5 h-3.5 text-brand-400" />
              <span>{userData.username}</span>
              <span className="text-emerald-400 font-mono">
                ${userData.wallets?.[0]?.balance?.toFixed(2) || "0.00"}
              </span>
            </Link>
          ) : (
            <Link
              href="/auth/login"
              className="bg-brand-600 hover:bg-brand-500 text-white text-xs font-semibold px-4 py-2 rounded-lg shadow-md shadow-brand-600/20 transition-all hover:scale-105"
            >
              Sign In
            </Link>
          )}

        </div>

        {/* Mobile menu button */}
        <div className="md:hidden flex items-center space-x-2">
          <select
            value={currentCurrency}
            onChange={(e) => setCurrency(e.target.value)}
            className="bg-slate-800 text-xs font-bold rounded px-1.5 py-1 text-slate-200"
          >
            {currencies.map((c) => (<option key={c} value={c}>{c}</option>))}
          </select>
          <button
            onClick={() => setIsMenuOpen(!isMenuOpen)}
            className="p-2 text-slate-400 hover:text-white"
          >
            {isMenuOpen ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
          </button>
        </div>

      </div>

      {/* Mobile Dropdown */}
      {isMenuOpen && (
        <div className="md:hidden px-4 pt-2 pb-4 space-y-2 bg-slate-900 border-b border-white/10">
          <Link href="/" onClick={() => setIsMenuOpen(false)} className="block py-2 text-slate-300">Destinations</Link>
          <Link href="/my-esims" onClick={() => setIsMenuOpen(false)} className="block py-2 text-slate-300">My eSIMs</Link>
          <Link href="/wallet" onClick={() => setIsMenuOpen(false)} className="block py-2 text-slate-300">Wallet</Link>
          {userData?.role === "SUPER_ADMIN" || userData?.role === "ADMIN" ? (
            <Link href="/admin" onClick={() => setIsMenuOpen(false)} className="block py-2 text-brand-400">Admin Console</Link>
          ) : null}
          <div className="pt-2 border-t border-slate-800">
            {token ? (
              <Link href="/profile" onClick={() => setIsMenuOpen(false)} className="block py-2 text-emerald-400">
                Account ({userData?.username})
              </Link>
            ) : (
              <Link href="/auth/login" onClick={() => setIsMenuOpen(false)} className="block py-2 text-brand-400 font-bold">
                Sign In / Register
              </Link>
            )}
          </div>
        </div>
      )}
    </header>
  );
}
