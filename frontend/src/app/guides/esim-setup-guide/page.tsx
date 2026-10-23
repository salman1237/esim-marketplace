import type { Metadata } from "next";
import Link from "next/link";
import { Apple, Smartphone, Wifi, QrCode, AlertTriangle } from "lucide-react";

export const metadata: Metadata = { title: "eSIM Setup Guide" };

const STEPS_IOS = [
  "Connect your iPhone to Wi-Fi (installing an eSIM needs an internet connection).",
  "Open the QR code from your order email, or open My eSIMs on this site and tap \"Install on iPhone\".",
  "Go to Settings → Cellular (or Mobile Service) → Add eSIM → Use QR Code, and scan it — or tap the install link directly from the email.",
  "Choose labels for your lines (e.g. keep your home line as default for calls/SMS, and use the new eSIM for data) under Settings → Cellular.",
  "Turn on Data Roaming for the new eSIM: Settings → Cellular → [your eSIM] → Network Selection / Data Roaming → On.",
  "That's it — your validity period starts counting once the eSIM connects to a network in your destination, not at install.",
];

const STEPS_ANDROID = [
  "Connect your Android phone to Wi-Fi.",
  "Open the QR code from your order email, or open My eSIMs on this site and tap \"Install on Android\" (on supported devices this installs directly, no scanning needed).",
  "Otherwise go to Settings → Network & internet → SIMs (or \"Connections\" → \"SIM card manager\" on Samsung) → Add eSIM / Download a SIM → scan the QR code.",
  "Make sure the new eSIM is enabled, and that mobile data + data roaming are turned on for it under its SIM settings.",
  "Set your preferred SIM for mobile data to the new eSIM so your phone actually uses it abroad.",
];

export default function EsimSetupGuidePage() {
  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
      <div className="flex items-center gap-3 mb-2">
        <div className="w-10 h-10 rounded-xl bg-brand-50 text-brand-600 flex items-center justify-center">
          <QrCode className="w-5 h-5" />
        </div>
        <h1 className="text-2xl sm:text-3xl font-extrabold text-slate-900">eSIM Setup Guide</h1>
      </div>
      <p className="text-sm text-slate-500 max-w-2xl">
        Takes about two minutes. Install it a day or two before you travel if you can — it won't start using up your
        validity until it actually connects to a network.
      </p>

      <div className="mt-6 rounded-2xl border border-amber-200 bg-amber-50 p-4 flex gap-3 text-xs text-amber-800">
        <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
        <span>
          An eSIM can only be installed <strong>once</strong>. If you delete it from your phone, it usually can't be
          reinstalled — check your plan details, and ask{" "}
          <Link href="/support" className="underline">Support</Link> before removing it.
        </span>
      </div>

      <div className="mt-8 grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="glass-panel rounded-2xl border border-gray-200 p-5">
          <div className="flex items-center gap-2 mb-3">
            <Apple className="w-4 h-4 text-slate-900" />
            <h2 className="text-sm font-bold text-slate-900">iPhone</h2>
          </div>
          <ol className="space-y-3">
            {STEPS_IOS.map((s, i) => (
              <li key={i} className="flex gap-3 text-xs text-slate-600">
                <span className="w-5 h-5 rounded-full bg-brand-100 text-brand-700 font-bold text-[11px] flex items-center justify-center shrink-0">{i + 1}</span>
                <span>{s}</span>
              </li>
            ))}
          </ol>
        </div>

        <div className="glass-panel rounded-2xl border border-gray-200 p-5">
          <div className="flex items-center gap-2 mb-3">
            <Smartphone className="w-4 h-4 text-emerald-600" />
            <h2 className="text-sm font-bold text-slate-900">Android</h2>
          </div>
          <ol className="space-y-3">
            {STEPS_ANDROID.map((s, i) => (
              <li key={i} className="flex gap-3 text-xs text-slate-600">
                <span className="w-5 h-5 rounded-full bg-emerald-100 text-emerald-700 font-bold text-[11px] flex items-center justify-center shrink-0">{i + 1}</span>
                <span>{s}</span>
              </li>
            ))}
          </ol>
          <p className="mt-3 text-[11px] text-slate-400">Menu names vary slightly by brand (Samsung, Xiaomi, Oppo, etc.) — look for "eSIM" or "Add SIM" under your SIM/network settings.</p>
        </div>
      </div>

      <div className="mt-8 glass-panel rounded-2xl border border-gray-200 p-5">
        <div className="flex items-center gap-2 mb-2">
          <Wifi className="w-4 h-4 text-brand-600" />
          <h2 className="text-sm font-bold text-slate-900">If it's not connecting</h2>
        </div>
        <ul className="list-disc list-inside space-y-1.5 text-xs text-slate-600">
          <li>Toggle Airplane Mode on and off, or restart your phone.</li>
          <li>Check the eSIM line has Data Roaming turned on — most data-only eSIMs need this explicitly enabled.</li>
          <li>Make sure the eSIM line (not your home SIM) is selected for mobile data.</li>
          <li>Check your eSIM's usage and expiry any time from the tracking link in your order email, or from <Link href="/my-esims" className="text-brand-600 hover:underline">My eSIMs</Link>.</li>
          <li>Still stuck? Contact <Link href="/support" className="text-brand-600 hover:underline">Support</Link> with your order number.</li>
        </ul>
      </div>

      <div className="mt-6">
        <Link href="/guides/compatible-phones" className="text-sm font-semibold text-brand-600 hover:underline">
          ← Check device compatibility
        </Link>
      </div>
    </div>
  );
}
