"use client";

import React, { useState, useEffect } from "react";
import { QrCode, Copy, Check, Info, Smartphone, ExternalLink } from "lucide-react";
import { QRCodeSVG } from "qrcode.react";
import { api } from "@/lib/api";

export default function MyESIMsPage() {
  const [esims, setEsims] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  useEffect(() => {
    const token = localStorage.getItem("esim_token");
    if (!token) {
      window.location.href = "/auth/login";
      return;
    }
    api.getMyESIMs(token)
      .then(setEsims)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  const copyToClipboard = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2500);
  };

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
      <div className="mb-8">
        <h1 className="text-3xl font-extrabold text-white">My eSIM Profiles</h1>
        <p className="text-xs text-slate-400 mt-1">
          Scan the QR code or manually install the LPA string in your phone's cellular settings.
        </p>
      </div>

      {loading ? (
        <div className="py-20 text-center text-sm text-slate-400">Loading your eSIM profiles...</div>
      ) : esims.length === 0 ? (
        <div className="glass-card rounded-2xl p-12 text-center">
          <QrCode className="w-12 h-12 text-slate-600 mx-auto mb-4" />
          <h3 className="text-lg font-bold text-white">No active eSIMs found</h3>
          <p className="text-xs text-slate-400 mt-1 mb-6">Browse our destination catalog to purchase your first high-speed data plan.</p>
          <a href="/" className="bg-brand-600 hover:bg-brand-500 text-white text-xs font-semibold px-4 py-2 rounded-xl">
            Explore Destinations
          </a>
        </div>
      ) : (
        <div className="space-y-6">
          {esims.map((item) => (
            <div key={item.id} className="glass-panel rounded-2xl p-6 border border-white/10 shadow-xl">
              
              <div className="flex flex-col md:flex-row items-center gap-8">
                
                {/* QR Code Card */}
                <div className="bg-white p-4 rounded-xl shadow-lg shrink-0 flex flex-col items-center">
                  <QRCodeSVG value={item.qr_code_data || item.lpa_string || "LPA:1$esim.local$demo"} size={160} level="M" />
                  <span className="text-[10px] font-bold text-slate-700 mt-2 uppercase tracking-wider">Scan with Camera</span>
                </div>

                {/* Profile Details */}
                <div className="flex-1 space-y-4 w-full">
                  <div className="flex items-center justify-between">
                    <div>
                      <h3 className="text-lg font-bold text-white">{item.product_title}</h3>
                      <p className="text-xs text-slate-400">{item.data_amount_gb} GB &bull; {item.validity_days} Days</p>
                    </div>
                    <span className="text-xs px-2.5 py-1 rounded-full font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                      {item.status}
                    </span>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                    <div className="bg-slate-900/60 p-2.5 rounded-lg border border-white/5">
                      <span className="text-slate-400 block text-[10px] uppercase font-semibold">ICCID</span>
                      <span className="font-mono text-slate-200">{item.iccid || "N/A"}</span>
                    </div>
                    <div className="bg-slate-900/60 p-2.5 rounded-lg border border-white/5">
                      <span className="text-slate-400 block text-[10px] uppercase font-semibold">Order ID</span>
                      <span className="font-mono text-slate-200">{item.order_no}</span>
                    </div>
                  </div>

                  {/* Manual LPA Copy Button */}
                  {item.lpa_string && (
                    <div>
                      <button
                        onClick={() => copyToClipboard(item.lpa_string, item.id)}
                        className="w-full flex items-center justify-center space-x-2 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold py-2 px-3 rounded-lg border border-white/10 transition-colors"
                      >
                        {copiedId === item.id ? (
                          <>
                            <Check className="w-3.5 h-3.5 text-emerald-400" />
                            <span className="text-emerald-400">LPA Code Copied to Clipboard!</span>
                          </>
                        ) : (
                          <>
                            <Copy className="w-3.5 h-3.5 text-slate-400" />
                            <span>Copy Manual Activation Code (LPA)</span>
                          </>
                        )}
                      </button>
                    </div>
                  )}

                  {/* Step-by-step installation guides */}
                  <div className="pt-2 border-t border-white/5 text-[11px] text-slate-400 space-y-1">
                    <div><strong>iOS:</strong> Settings &gt; Cellular &gt; Add eSIM &gt; Scan QR Code</div>
                    <div><strong>Android:</strong> Settings &gt; Network &amp; Internet &gt; SIMs &gt; Add &gt; Scan QR Code</div>
                  </div>

                </div>

              </div>

            </div>
          ))}
        </div>
      )}
    </div>
  );
}
