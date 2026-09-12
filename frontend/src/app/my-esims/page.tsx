"use client";

import React, { useState, useEffect } from "react";
import { QrCode, Copy, Check, Smartphone, Sparkles, Clock, Printer } from "lucide-react";
import { QRCodeSVG } from "qrcode.react";
import { motion, AnimatePresence } from "framer-motion";
import confetti from "canvas-confetti";
import { api } from "@/lib/api";
import { useAppSettings } from "@/lib/AppSettingsContext";
import { EsimListSkeleton } from "@/components/Skeleton";
import { esimInstallLinks } from "@/lib/esimInstall";
import { waitForOrder } from "@/lib/waitForOrder";

function EsimCard({ item }: { item: any }) {
  const { t } = useAppSettings();
  const [revealed, setRevealed] = useState(false);
  const [copied, setCopied] = useState(false);
  const [guideTab, setGuideTab] = useState<"ios" | "android">("ios");

  const handleReveal = () => {
    setRevealed(true);
    confetti({
      particleCount: 90,
      spread: 70,
      origin: { y: 0.6 },
      colors: ["#6366f1", "#22d3ee", "#a5b4fc"],
    });
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2500);
  };

  return (
    <div className="glass-panel rounded-2xl p-6 border border-gray-200 shadow-md" style={{ perspective: 1200 }}>
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-lg font-bold text-slate-900">{item.product_title}</h3>
          <p className="text-xs text-slate-500">{item.is_unlimited ? "Unlimited" : `${item.data_amount_gb} GB`} &bull; {item.validity_days} Days</p>
        </div>
        {item.is_mock_fallback ? (
          <span className="text-xs px-2.5 py-1 rounded-full font-bold bg-amber-50 text-amber-700 border border-amber-200 flex items-center gap-1">
            <Clock className="w-3 h-3" /> Activation Pending
          </span>
        ) : (
          <span className="text-xs px-2.5 py-1 rounded-full font-bold bg-emerald-50 text-emerald-700 border border-emerald-200">
            {item.status}
          </span>
        )}
      </div>

      <AnimatePresence mode="wait">
        {!revealed ? (
          <motion.button
            key="cover"
            onClick={handleReveal}
            initial={{ rotateY: 0 }}
            exit={{ rotateY: 90, opacity: 0 }}
            transition={{ duration: 0.35 }}
            className="w-full flex flex-col items-center justify-center gap-3 py-12 rounded-xl bg-gradient-to-br from-brand-50 to-accent-50 border border-gray-200 hover:border-brand-300 transition-colors"
          >
            <Sparkles className="w-8 h-8 text-brand-600" />
            <span className="text-sm font-bold text-slate-900">{t("esim", "ready_title", "Your eSIM is Ready to Install!")}</span>
            <span className="text-xs text-slate-500">Tap to reveal your QR code</span>
          </motion.button>
        ) : (
          <motion.div
            key="revealed"
            initial={{ rotateY: -90, opacity: 0 }}
            animate={{ rotateY: 0, opacity: 1 }}
            transition={{ duration: 0.4 }}
          >
            <div className="flex flex-col md:flex-row items-center gap-8">
              <div className="bg-white p-4 rounded-xl border border-gray-200 shadow-sm shrink-0 flex flex-col items-center">
                <QRCodeSVG value={item.qr_code_data || item.lpa_string || "LPA:1$esim.local$demo"} size={160} level="M" />
                <span className="text-[10px] font-bold text-slate-700 mt-2 uppercase tracking-wider">{t("esim", "scan_qr", "Scan this QR Code")}</span>
              </div>

              <div className="flex-1 space-y-4 w-full">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                  <div className="bg-gray-50 p-2.5 rounded-lg border border-gray-200">
                    <span className="text-slate-500 block text-[10px] uppercase font-semibold">{t("esim", "iccid", "ICCID")}</span>
                    <span className="font-mono text-slate-900">{item.iccid || "N/A"}</span>
                  </div>
                  <div className="bg-gray-50 p-2.5 rounded-lg border border-gray-200">
                    <span className="text-slate-500 block text-[10px] uppercase font-semibold">Order ID</span>
                    <span className="font-mono text-slate-900">{item.order_no}</span>
                  </div>
                </div>

                {(() => {
                  const install = esimInstallLinks(item.lpa_string);
                  if (!install.ios && !install.android) return null;
                  return (
                    <div>
                      <div className="flex gap-2">
                        {install.ios && (
                          <a
                            href={install.ios}
                            className="flex-1 flex items-center justify-center gap-1.5 bg-slate-900 hover:bg-slate-800 text-white text-xs font-bold py-2 px-3 rounded-lg transition-colors"
                          >
                            <Smartphone className="w-3.5 h-3.5" /> Install on iPhone
                          </a>
                        )}
                        {install.android && (
                          <a
                            href={install.android}
                            className="flex-1 flex items-center justify-center gap-1.5 bg-emerald-500 hover:bg-emerald-400 text-slate-900 text-xs font-bold py-2 px-3 rounded-lg transition-colors"
                          >
                            <Smartphone className="w-3.5 h-3.5" /> Install on Android
                          </a>
                        )}
                      </div>
                      <p className="text-[10px] text-slate-500 mt-1.5">
                        Tap on the phone that will use the eSIM (iOS 17.4+ / recent Android). Otherwise scan the QR code.
                      </p>
                    </div>
                  );
                })()}

                <a
                  href={`/my-esims/${item.id}/print`}
                  className="w-full flex items-center justify-center space-x-2 bg-white hover:bg-gray-50 text-slate-700 text-xs font-semibold py-2 px-3 rounded-lg border border-gray-300 transition-colors"
                >
                  <Printer className="w-3.5 h-3.5 text-slate-500" />
                  <span>Print / Save as PDF</span>
                </a>

                {item.lpa_string && (
                  <button
                    onClick={() => copyToClipboard(item.lpa_string)}
                    className="w-full flex items-center justify-center space-x-2 bg-gray-100 hover:bg-gray-200 text-slate-700 text-xs font-semibold py-2 px-3 rounded-lg border border-gray-200 transition-colors"
                  >
                    {copied ? (
                      <>
                        <Check className="w-3.5 h-3.5 text-emerald-600" />
                        <span className="text-emerald-600">Copied to Clipboard!</span>
                      </>
                    ) : (
                      <>
                        <Copy className="w-3.5 h-3.5 text-slate-500" />
                        <span>{t("esim", "copy_code", "Copy LPA Code")}</span>
                      </>
                    )}
                  </button>
                )}

                <div className="pt-2 border-t border-gray-200">
                  <div className="flex gap-2 mb-2">
                    <button
                      onClick={() => setGuideTab("ios")}
                      className={`flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-lg text-[11px] font-bold transition-colors ${guideTab === "ios" ? "bg-brand-600 text-white" : "bg-gray-100 text-slate-500"}`}
                    >
                      <Smartphone className="w-3 h-3" /> iOS
                    </button>
                    <button
                      onClick={() => setGuideTab("android")}
                      className={`flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-lg text-[11px] font-bold transition-colors ${guideTab === "android" ? "bg-brand-600 text-white" : "bg-gray-100 text-slate-500"}`}
                    >
                      <Smartphone className="w-3 h-3" /> Android
                    </button>
                  </div>
                  <p className="text-[11px] text-slate-500">
                    {guideTab === "ios"
                      ? t("esim", "ios_guide", "iOS: Settings > Cellular > Add eSIM > Scan QR")
                      : t("esim", "android_guide", "Android: Settings > Network & Internet > SIMs > Add > Scan QR")}
                  </p>
                </div>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export default function MyESIMsPage() {
  const [esims, setEsims] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [paymentBanner, setPaymentBanner] = useState<
    { kind: "processing" | "success" | "failed" | "slow"; reason?: string } | null
  >(null);

  useEffect(() => {
    const token = localStorage.getItem("esim_token");
    if (!token) {
      window.location.href = "/auth/login";
      return;
    }

    const loadEsims = () =>
      api.getMyESIMs(token)
        .then(setEsims)
        .catch(console.error)
        .finally(() => setLoading(false));

    // ShurjoPay redirects the browser back here after a direct-gateway
    // eSIM purchase — see GET /api/v1/payments/shurjopay/callback. A paid
    // order arrives as ?order=<id> while its eSIM is still being set up in
    // the background, so poll it and refresh the list once it settles.
    const params = new URLSearchParams(window.location.search);
    const orderId = params.get("order");
    const payment = params.get("payment");
    if (orderId || payment) {
      window.history.replaceState({}, "", window.location.pathname);
    }
    if (orderId) {
      setPaymentBanner({ kind: "processing" });
      waitForOrder(token, orderId)
        .then((order) => {
          setPaymentBanner({ kind: order.status === "COMPLETED" ? "success" : "failed", reason: order.status === "COMPLETED" ? undefined : "provisioning_failed_refunded" });
          loadEsims();
        })
        .catch(() => setPaymentBanner({ kind: "slow" }));
    } else if (payment === "success" || payment === "failed") {
      setPaymentBanner({ kind: payment, reason: params.get("reason") || undefined });
    }

    loadEsims();
  }, []);

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
      <div className="mb-8">
        <h1 className="text-3xl font-extrabold text-slate-900">My eSIM Profiles</h1>
        <p className="text-xs text-slate-500 mt-1">
          Scan the QR code or manually install the LPA string in your phone's cellular settings.
        </p>
      </div>

      {paymentBanner && (
        <div className={`mb-6 p-3 rounded-xl border text-xs font-medium flex items-center gap-2 ${
          paymentBanner.kind === "success"
            ? "bg-emerald-50 border-emerald-200 text-emerald-700"
            : paymentBanner.kind === "processing" || paymentBanner.kind === "slow"
            ? "bg-brand-50 border-brand-200 text-brand-700"
            : "bg-rose-50 border-rose-200 text-rose-700"
        }`}>
          {paymentBanner.kind === "processing" && (
            <span className="w-4 h-4 rounded-full border-2 border-brand-600 border-t-transparent animate-spin shrink-0" />
          )}
          {paymentBanner.kind === "processing"
            ? "Payment received — setting up your eSIM. This usually takes 10–20 seconds."
            : paymentBanner.kind === "slow"
            ? "Payment received — your eSIM is taking longer than usual to set up. Refresh this page in a minute; you'll also get it by email."
            : paymentBanner.kind === "success"
            ? "Payment received — your eSIM is ready below."
            : paymentBanner.reason === "provisioning_failed_refunded"
            ? "Your payment went through, but eSIM provisioning failed. The full amount has been refunded to your wallet balance."
            : `Payment was not completed${paymentBanner.reason ? ` (${paymentBanner.reason.replace(/_/g, " ")})` : ""}. No charge was made.`}
        </div>
      )}

      {loading ? (
        <EsimListSkeleton />
      ) : esims.length === 0 ? (
        <div className="glass-card rounded-2xl p-12 text-center">
          <QrCode className="w-12 h-12 text-slate-300 mx-auto mb-4" />
          <h3 className="text-lg font-bold text-slate-900">No active eSIMs found</h3>
          <p className="text-xs text-slate-500 mt-1 mb-6">Browse our destination catalog to purchase your first high-speed data plan.</p>
          <a href="/" className="bg-brand-600 hover:bg-brand-500 text-white text-xs font-semibold px-4 py-2 rounded-xl">
            Explore Destinations
          </a>
        </div>
      ) : (
        <div className="space-y-6">
          {esims.map((item) => (
            <EsimCard key={item.id} item={item} />
          ))}
        </div>
      )}
    </div>
  );
}
