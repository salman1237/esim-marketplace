"use client";

import React from "react";
import Link from "next/link";
import { Wifi, Phone, Mail, MessageCircle, ShieldCheck, Globe2 } from "lucide-react";

export default function Footer() {
  return (
    <footer className="bg-slate-950 border-t border-white/10 text-slate-400 text-sm mt-20">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-12 grid grid-cols-1 md:grid-cols-4 gap-8">
        
        {/* Col 1: Brand & Tagline */}
        <div className="space-y-4">
          <div className="flex items-center space-x-3">
            <div className="w-8 h-8 rounded-lg bg-brand-600 flex items-center justify-center">
              <Wifi className="w-4 h-4 text-white" />
            </div>
            <span className="text-lg font-bold text-white">eSIM Global</span>
          </div>
          <p className="text-xs text-slate-400 leading-relaxed">
            Instant global connectivity across 200+ countries. Zero roaming fees, instant QR delivery, and flexible digital data.
          </p>
          <div className="flex items-center space-x-2 text-xs text-emerald-400">
            <ShieldCheck className="w-4 h-4" />
            <span>Official VivaPe & ShurjoPay Partner</span>
          </div>
        </div>

        {/* Col 2: Quick Links */}
        <div className="space-y-3">
          <h4 className="text-xs font-bold text-white uppercase tracking-wider">Explore</h4>
          <ul className="space-y-2 text-xs">
            <li><Link href="/" className="hover:text-white">Popular Destinations</Link></li>
            <li><Link href="/my-esims" className="hover:text-white">My eSIM Profiles</Link></li>
            <li><Link href="/wallet" className="hover:text-white">Wallet & Top Up</Link></li>
            <li><Link href="/reseller" className="hover:text-white">B2B Reseller Program</Link></li>
          </ul>
        </div>

        {/* Col 3: Legal & Support */}
        <div className="space-y-3">
          <h4 className="text-xs font-bold text-white uppercase tracking-wider">Support</h4>
          <ul className="space-y-2 text-xs">
            <li><a href="mailto:support@esim.local" className="flex items-center space-x-2 hover:text-white"><Mail className="w-3.5 h-3.5" /><span>support@esim.local</span></a></li>
            <li><a href="https://wa.me/8801700000000" target="_blank" rel="noreferrer" className="flex items-center space-x-2 hover:text-white text-emerald-400"><MessageCircle className="w-3.5 h-3.5" /><span>24/7 WhatsApp Support</span></a></li>
            <li><span className="flex items-center space-x-2 text-slate-400"><Phone className="w-3.5 h-3.5" /><span>+880 1700-000000</span></span></li>
          </ul>
        </div>

        {/* Col 4: International */}
        <div className="space-y-3">
          <h4 className="text-xs font-bold text-white uppercase tracking-wider">Global Reach</h4>
          <p className="text-xs leading-relaxed text-slate-400">
            Available in English, বাংলা, العربية, and Español. Multi-currency settlement in USD, BDT, EUR, GBP, and SAR.
          </p>
          <div className="flex items-center space-x-2 text-xs text-slate-500">
            <Globe2 className="w-4 h-4 text-brand-400" />
            <span>200+ Countries Covered</span>
          </div>
        </div>

      </div>

      <div className="border-t border-white/5 py-6 text-center text-xs text-slate-500">
        &copy; {new Date().getFullYear()} eSIM Global Platform. All rights reserved. Powered by Dokploy VPS.
      </div>
    </footer>
  );
}
