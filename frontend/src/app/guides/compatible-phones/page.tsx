import type { Metadata } from "next";
import Link from "next/link";
import { CheckCircle2, Smartphone, PhoneCall } from "lucide-react";

export const metadata: Metadata = { title: "eSIM Compatible Phones" };

// A reference list, not pulled from a device database - new models are
// added by editing this file. Kept short and grouped by brand so a visitor
// can scan it on a phone screen in a few seconds, which is who's actually
// reading this page.
const DEVICES: { brand: string; models: string[] }[] = [
  {
    brand: "Apple iPhone",
    models: [
      "iPhone 17, 17 Pro, 17 Pro Max, Air",
      "iPhone 16 series (including 16e)",
      "iPhone 15 series",
      "iPhone 14 series",
      "iPhone 13 series",
      "iPhone 12 series",
      "iPhone 11 series",
      "iPhone XS, XS Max, XR",
      "iPhone SE (2020 and later)",
    ],
  },
  {
    brand: "Samsung Galaxy",
    models: [
      "Galaxy S25 / S24 / S23 / S22 / S21 / S20 series",
      "Galaxy Z Fold 3 and later, Z Flip 3 and later",
      "Galaxy Note 20 series",
    ],
  },
  {
    brand: "Google Pixel",
    models: ["Pixel 9 series", "Pixel 8 series", "Pixel 7 series", "Pixel 6 series", "Pixel 5", "Pixel 4 / 4a", "Pixel 3 / 3a"],
  },
  {
    brand: "Other popular models",
    models: [
      "Huawei P40, Mate 40 series and later",
      "Oppo Find X3, X5, X7 series",
      "Sony Xperia 10 IV and later, Xperia 1 IV and later",
      "Motorola Razr (2019 and later), Edge 40/50 series",
      "Honor Magic series, Honor 90 and later",
    ],
  },
];

export default function CompatiblePhonesPage() {
  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
      <div className="flex items-center gap-3 mb-2">
        <div className="w-10 h-10 rounded-xl bg-brand-50 text-brand-600 flex items-center justify-center">
          <Smartphone className="w-5 h-5" />
        </div>
        <h1 className="text-2xl sm:text-3xl font-extrabold text-slate-900">eSIM Compatible Phones</h1>
      </div>
      <p className="text-sm text-slate-500 max-w-2xl">
        Before you buy, make sure your phone supports eSIM <strong>and</strong> is not carrier-locked — a locked
        phone usually can't add a second carrier's eSIM even on a supported model.
      </p>

      <div className="mt-6 rounded-2xl border border-emerald-200 bg-emerald-50 p-5">
        <div className="flex items-center gap-2 mb-2">
          <PhoneCall className="w-4 h-4 text-emerald-700" />
          <h2 className="text-sm font-bold text-emerald-900">The fastest way to check: dial *#06#</h2>
        </div>
        <p className="text-xs text-emerald-800 leading-relaxed">
          Open your phone's dialer and dial <strong className="font-mono">*#06#</strong> — no need to press call.
          A screen with your device's ID numbers will pop up. If you see a line labelled{" "}
          <strong>EID</strong>, your phone supports eSIM. If there's no EID shown, only an IMEI, your phone can't use
          an eSIM.
        </p>
        <div className="mt-4 rounded-xl overflow-hidden bg-black max-w-xs">
          <video
            src="/guides/check-esim-support.mp4"
            controls
            playsInline
            preload="metadata"
            className="w-full h-auto block"
          >
            Your browser doesn't support inline video — dial *#06# on your phone and look for &ldquo;EID&rdquo;.
          </video>
        </div>
        <p className="mt-2 text-[11px] text-emerald-700">Watch: how to dial *#06# and spot the EID line.</p>
      </div>

      <div className="mt-6 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-xs text-amber-800">
        <strong>Still not sure?</strong> On iPhone: Settings → General → About → look for &ldquo;Digital SIM&rdquo; or
        check your carrier. On Android: Settings → Network &amp; internet → SIMs → look for an &ldquo;Add eSIM&rdquo;
        or &ldquo;Download a SIM&rdquo; option. If it's missing, your device or region variant likely doesn't support eSIM.
      </div>

      <div className="mt-8 grid grid-cols-1 sm:grid-cols-2 gap-6">
        {DEVICES.map((group) => (
          <div key={group.brand} className="glass-panel rounded-2xl border border-gray-200 p-5">
            <h2 className="text-sm font-bold text-slate-900 mb-3">{group.brand}</h2>
            <ul className="space-y-2">
              {group.models.map((m) => (
                <li key={m} className="flex items-start gap-2 text-xs text-slate-600">
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600 shrink-0 mt-0.5" />
                  <span>{m}</span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      <p className="mt-8 text-xs text-slate-500">
        This list covers the devices we see most often — it isn't exhaustive. If your model isn't listed, check the
        manufacturer's own eSIM support page, or ask us before buying via{" "}
        <Link href="/support" className="text-brand-600 hover:underline">Support</Link>.
      </p>

      <div className="mt-6">
        <Link href="/guides/esim-setup-guide" className="text-sm font-semibold text-brand-600 hover:underline">
          Next: how to install your eSIM →
        </Link>
      </div>
    </div>
  );
}
