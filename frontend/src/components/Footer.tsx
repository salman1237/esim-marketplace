"use client";

import React from "react";
import Link from "next/link";
import { Wifi, Phone, Mail, MessageCircle, ShieldCheck, Briefcase, ArrowRight, Facebook, Instagram, Twitter, Youtube, Linkedin } from "lucide-react";
import { API_BASE } from "@/lib/api";
import { useAppSettings } from "@/lib/AppSettingsContext";
import PartnerCta from "@/components/PartnerCta";

// Kept in step with LEGAL_TITLES in the backend's legal_content_svc - the
// pages themselves are edited from the admin console.
const LEGAL_LINKS = [
  { href: "/legal/privacy", label: "Privacy Policy" },
  { href: "/legal/data-policy", label: "Data Privacy" },
  { href: "/legal/terms", label: "Terms & Conditions" },
  { href: "/legal/declaration", label: "Declaration" },
  { href: "/legal/refund-policy", label: "Refund Policy" },
  { href: "/legal/payment-policy", label: "Payment Policy" },
];

export default function Footer() {
  const { t, publicSettings } = useAppSettings();
  // Server-rendered branding from the root layout - no placeholder brand
  // name or contact details that flash before the real ones load.
  const settings = publicSettings || {};

  const whatsappDigits = (settings.support_whatsapp || "").replace(/[^0-9]/g, "");
  const socialLinks: Record<string, string> = settings.social_links || {};
  const SOCIAL_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
    facebook: Facebook, instagram: Instagram, twitter: Twitter, youtube: Youtube, linkedin: Linkedin,
  };

  const heading = "text-xs font-bold text-slate-900 uppercase tracking-wider";
  const link = "text-slate-500 hover:text-slate-900 transition-colors";

  return (
    <footer className="bg-white border-t border-gray-200 text-sm mt-20 print:hidden">
      {/* Partner call-to-action - the B2B program gets its own band, not a
          buried link. */}
      <div className="bg-gradient-to-r from-merchant-600 to-brand-600">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 flex flex-col sm:flex-row sm:items-center justify-between gap-4 text-white">
          <div className="flex items-center gap-3">
            <span className="w-10 h-10 rounded-xl bg-white/15 flex items-center justify-center shrink-0">
              <Briefcase className="w-5 h-5" />
            </span>
            <div>
              <div className="text-sm font-bold">Travel agency or reseller?</div>
              <div className="text-xs text-white/80">Earn commission on every eSIM you sell — from your dashboard or our API.</div>
            </div>
          </div>
          <div className="shrink-0">
            <PartnerCta size="sm" guestPrimary={{ label: "Become a partner", href: "/partners", icon: ArrowRight }} />
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-12 grid grid-cols-2 md:grid-cols-6 gap-8">

        {/* Brand */}
        <div className="col-span-2 space-y-4">
          <div className="flex items-center space-x-3">
            {/* Logo already carries the brand name - see Header.tsx. */}
            {settings.logo_light ? (
              <img
                src={settings.logo_light.startsWith("http") ? settings.logo_light : `${API_BASE}${settings.logo_light}`}
                alt={settings.platform_name || ""}
                className="h-8 max-w-[160px] w-auto object-contain"
              />
            ) : settings.platform_name ? (
              <>
                <div className="w-8 h-8 rounded-lg bg-brand-600 flex items-center justify-center">
                  <Wifi className="w-4 h-4 text-white" />
                </div>
                <span className="text-lg font-bold text-slate-900">{settings.platform_name}</span>
              </>
            ) : null}
          </div>
          <p className="text-xs text-slate-500 leading-relaxed max-w-xs">
            {settings.tagline_en || "Instant global connectivity across 200+ countries. Zero roaming fees, instant QR delivery, and flexible digital data."}
          </p>
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

        {/* Explore */}
        <div className="space-y-3">
          <h4 className={heading}>{t("common", "explore", "Explore")}</h4>
          <ul className="space-y-2 text-xs">
            <li><Link href="/destinations" className={link}>All Destinations</Link></li>
            <li><Link href="/my-esims" className={link}>{t("common", "my_esims", "My eSIMs")}</Link></li>
            <li><Link href="/wallet" className={link}>{t("common", "wallet", "Wallet")} &amp; Top Up</Link></li>
            <li><Link href="/refer" className={link}>Refer &amp; Earn</Link></li>
          </ul>
        </div>

        {/* For business */}
        <div className="space-y-3">
          <h4 className={heading}>For Business</h4>
          <ul className="space-y-2 text-xs">
            <li><Link href="/partners" className="font-semibold text-merchant-600 hover:text-merchant-700">B2B Partner Program</Link></li>
            <li><Link href="/reseller" className={link}>Partner Portal</Link></li>
            <li><Link href="/agent" className={link}>Become an Agent</Link></li>
            <li><Link href="/api-docs" className={link}>API Documentation</Link></li>
          </ul>
        </div>

        {/* Support */}
        <div className="space-y-3">
          <h4 className={heading}>{t("nav", "support", "Support")}</h4>
          <ul className="space-y-2 text-xs">
            {settings.support_email && (
              <li><a href={`mailto:${settings.support_email}`} className={`flex items-center gap-2 ${link}`}><Mail className="w-3.5 h-3.5 shrink-0" /><span className="truncate">{settings.support_email}</span></a></li>
            )}
            {whatsappDigits && (
              <li><a href={`https://wa.me/${whatsappDigits}`} target="_blank" rel="noreferrer" className="flex items-center gap-2 text-emerald-600 hover:text-emerald-700"><MessageCircle className="w-3.5 h-3.5 shrink-0" /><span>WhatsApp Support</span></a></li>
            )}
            {settings.support_phone && (
              <li><span className="flex items-center gap-2 text-slate-500"><Phone className="w-3.5 h-3.5 shrink-0" /><span>{settings.support_phone}</span></span></li>
            )}
          </ul>
        </div>

        {/* Legal */}
        <div className="space-y-3">
          <h4 className={heading}>Legal</h4>
          <ul className="space-y-2 text-xs">
            {LEGAL_LINKS.map((l) => (
              <li key={l.href}><Link href={l.href} className={link}>{l.label}</Link></li>
            ))}
          </ul>
        </div>
      </div>

      <div className="border-t border-gray-100">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-5 flex flex-col sm:flex-row items-center justify-between gap-2 text-xs text-slate-500">
          <span>&copy; {new Date().getFullYear()}{settings.platform_name ? ` ${settings.platform_name}` : ""}. All rights reserved.</span>
          <span className="flex items-center gap-1.5">
            <ShieldCheck className="w-3.5 h-3.5 text-emerald-600" />
            Secure payments by ShurjoPay · bKash · Nagad · Visa · Mastercard
          </span>
        </div>
      </div>
    </footer>
  );
}
