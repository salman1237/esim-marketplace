"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { Wifi, Phone, Mail, MessageCircle, ShieldCheck, Globe2, Facebook, Instagram, Twitter, Youtube, Linkedin } from "lucide-react";
import { api, API_BASE } from "@/lib/api";
import { useAppSettings } from "@/lib/AppSettingsContext";

export default function Footer() {
  const { t } = useAppSettings();
  const [settings, setSettings] = useState<any>({
    platform_name: "eSIM Global",
    support_email: "support@esim.local",
    support_phone: "+880 1700-000000",
    support_whatsapp: "+880 1700-000000",
  });

  useEffect(() => {
    api.getPublicSettings().then(setSettings).catch(() => {});
  }, []);

  const whatsappDigits = (settings.support_whatsapp || "").replace(/[^0-9]/g, "");
  const socialLinks: Record<string, string> = settings.social_links || {};
  const SOCIAL_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
    facebook: Facebook, instagram: Instagram, twitter: Twitter, youtube: Youtube, linkedin: Linkedin,
  };

  return (
    <footer className="bg-white border-t border-gray-200 text-slate-500 text-sm mt-20">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-12 grid grid-cols-1 md:grid-cols-4 gap-8">

        {/* Col 1: Brand & Tagline */}
        <div className="space-y-4">
          <div className="flex items-center space-x-3">
            {settings.logo_light ? (
              <img
                src={settings.logo_light.startsWith("http") ? settings.logo_light : `${API_BASE}${settings.logo_light}`}
                alt={settings.platform_name || "eSIM Global"}
                className="w-8 h-8 rounded-lg object-contain"
              />
            ) : (
              <div className="w-8 h-8 rounded-lg bg-brand-600 flex items-center justify-center">
                <Wifi className="w-4 h-4 text-white" />
              </div>
            )}
            <span className="text-lg font-bold text-slate-900">{settings.platform_name || "eSIM Global"}</span>
          </div>
          <p className="text-xs text-slate-500 leading-relaxed">
            {settings.tagline_en || "Instant global connectivity across 200+ countries. Zero roaming fees, instant QR delivery, and flexible digital data."}
          </p>
          <div className="flex items-center space-x-2 text-xs text-emerald-600">
            <ShieldCheck className="w-4 h-4" />
            <span>Official VivaPe & ShurjoPay Partner</span>
          </div>
          {Object.keys(socialLinks).some((k) => socialLinks[k]) && (
            <div className="flex items-center space-x-3 pt-1">
              {Object.entries(socialLinks).filter(([, url]) => url).map(([platform, url]) => {
                const Icon = SOCIAL_ICONS[platform];
                if (!Icon) return null;
                return (
                  <a key={platform} href={url} target="_blank" rel="noreferrer" aria-label={platform} className="text-slate-500 hover:text-slate-900 transition-colors">
                    <Icon className="w-4 h-4" />
                  </a>
                );
              })}
            </div>
          )}
        </div>

        {/* Col 2: Quick Links */}
        <div className="space-y-3">
          <h4 className="text-xs font-bold text-slate-900 uppercase tracking-wider">{t("common", "explore", "Explore")}</h4>
          <ul className="space-y-2 text-xs">
            <li><Link href="/" className="hover:text-slate-900">Popular Destinations</Link></li>
            <li><Link href="/my-esims" className="hover:text-slate-900">{t("common", "my_esims", "My eSIMs")}</Link></li>
            <li><Link href="/wallet" className="hover:text-slate-900">{t("common", "wallet", "Wallet")} & Top Up</Link></li>
            <li><Link href="/reseller" className="hover:text-slate-900">B2B Reseller Program</Link></li>
            <li><Link href="/api-docs" className="hover:text-slate-900">API Documentation</Link></li>
          </ul>
        </div>

        {/* Col 3: Legal & Support */}
        <div className="space-y-3">
          <h4 className="text-xs font-bold text-slate-900 uppercase tracking-wider">{t("nav", "support", "Support")}</h4>
          <ul className="space-y-2 text-xs">
            <li><a href={`mailto:${settings.support_email}`} className="flex items-center space-x-2 hover:text-slate-900"><Mail className="w-3.5 h-3.5" /><span>{settings.support_email}</span></a></li>
            {whatsappDigits && (
              <li><a href={`https://wa.me/${whatsappDigits}`} target="_blank" rel="noreferrer" className="flex items-center space-x-2 hover:text-emerald-700 text-emerald-600"><MessageCircle className="w-3.5 h-3.5" /><span>24/7 WhatsApp Support</span></a></li>
            )}
            <li><span className="flex items-center space-x-2 text-slate-500"><Phone className="w-3.5 h-3.5" /><span>{settings.support_phone}</span></span></li>
          </ul>
        </div>

        {/* Col 4: International */}
        <div className="space-y-3">
          <h4 className="text-xs font-bold text-slate-900 uppercase tracking-wider">Global Reach</h4>
          <p className="text-xs leading-relaxed text-slate-500">
            Available in English, বাংলা, العربية, and Español. Multi-currency settlement in USD, BDT, EUR, GBP, and SAR.
          </p>
          <div className="flex items-center space-x-2 text-xs text-slate-500">
            <Globe2 className="w-4 h-4 text-brand-600" />
            <span>200+ Countries Covered</span>
          </div>
        </div>

      </div>

      <div className="border-t border-gray-100 py-6 text-center text-xs text-slate-500">
        &copy; {new Date().getFullYear()} {settings.platform_name || "eSIM Global"} Platform. All rights reserved.
      </div>
    </footer>
  );
}
