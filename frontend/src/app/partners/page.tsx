import type { Metadata } from "next";
import Link from "next/link";
import PartnerCta from "@/components/PartnerCta";
import {
  BadgePercent, Briefcase, Code2, FileText, Globe2, LayoutDashboard, Send, ShieldCheck, Wallet, Zap,
} from "lucide-react";

export const metadata: Metadata = {
  title: "B2B Partner Program — sell travel eSIMs and earn commission",
  description:
    "For travel agencies and resellers: issue travel eSIMs to your customers in 190+ countries, earn commission on every sale, and integrate with our Partner API.",
};

const BENEFITS = [
  { icon: BadgePercent, title: "Commission on every sale", text: "Earn a percentage of every eSIM you issue, credited when it's delivered. Higher volume unlocks higher rates." },
  { icon: Zap, title: "Issue in seconds", text: "Pick a country and package, enter your customer's email, and the QR code is delivered straight to them." },
  { icon: Globe2, title: "190+ destinations", text: "One catalogue for every trip you sell — single countries, regions and global plans, 4G and 5G." },
  { icon: Code2, title: "Partner API", text: "Sell from your own website or booking system. Token auth, idempotent orders and signed webhooks." },
  { icon: FileText, title: "Monthly statements", text: "Every top-up, sale, refund and commission, with opening and closing balances you can reconcile." },
  { icon: Wallet, title: "Pay your way", text: "Prepay a wallet for instant issuing, or pay per order by bKash, Nagad or card." },
];

const STEPS = [
  { title: "Create an account", text: "Sign up with your email or Google in under a minute." },
  { title: "Apply as a partner", text: "Tell us your business name, trade licence and contact number." },
  { title: "Get approved", text: "We review your application and set your commission rate." },
  { title: "Start selling", text: "Issue eSIMs from your partner dashboard, or connect the API." },
];

const FAQ = [
  { q: "Who can join?", a: "Travel agencies, tour operators, ticketing agents and any business that sells to travellers. A trade licence or corporate ID is required." },
  { q: "How is commission paid?", a: "Commission is credited to your commission wallet as each eSIM is delivered. A refunded order doesn't earn commission." },
  { q: "Do I need to be technical?", a: "No. The partner dashboard works from any browser. The API is optional, for partners who want to sell from their own system." },
  { q: "What do my customers receive?", a: "A QR code and one-tap install links by email, with step-by-step setup instructions." },
];

export default function PartnersPage() {
  return (
    <div className="space-y-20 pb-8">
      {/* Hero */}
      <section className="bg-gradient-to-br from-merchant-600 via-brand-600 to-indigo-700 text-white">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-16 sm:py-20 grid grid-cols-1 lg:grid-cols-[1.2fr_1fr] gap-10 items-center">
          <div>
            <span className="inline-flex items-center gap-2 bg-white/15 text-xs font-semibold px-3 py-1.5 rounded-full">
              <Briefcase className="w-3.5 h-3.5" /> B2B Partner Program
            </span>
            <h1 className="mt-5 text-4xl sm:text-5xl font-extrabold leading-tight">
              Sell travel eSIMs to your customers. Earn on every one.
            </h1>
            <p className="mt-4 text-base text-white/85 max-w-xl">
              Add instant mobile data to every ticket and tour you sell. Issue eSIMs from your own dashboard or through our API,
              and earn commission on each delivery.
            </p>
            <div className="mt-8">
              <PartnerCta showNote />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            {[
              { k: "190+", v: "destinations" },
              { k: "Instant", v: "QR delivery" },
              { k: "Commission", v: "on every sale" },
              { k: "API", v: "+ dashboard" },
            ].map((s) => (
              <div key={s.v} className="rounded-2xl bg-white/10 border border-white/20 p-5">
                <div className="text-2xl font-black">{s.k}</div>
                <div className="text-xs text-white/80 mt-1">{s.v}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Benefits */}
      <section className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
        <h2 className="text-2xl sm:text-3xl font-extrabold text-slate-900 text-center">Why partner with us</h2>
        <p className="text-sm text-slate-500 text-center mt-2 max-w-2xl mx-auto">Everything a travel business needs to add eSIMs to what it already sells.</p>
        <div className="mt-10 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {BENEFITS.map(({ icon: Icon, title, text }) => (
            <div key={title} className="glass-panel rounded-2xl border border-gray-200 p-6">
              <span className="w-10 h-10 rounded-xl bg-merchant-50 text-merchant-600 flex items-center justify-center">
                <Icon className="w-5 h-5" />
              </span>
              <h3 className="mt-4 text-base font-bold text-slate-900">{title}</h3>
              <p className="mt-1 text-xs text-slate-500 leading-relaxed">{text}</p>
            </div>
          ))}
        </div>
      </section>

      {/* How it works */}
      <section className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
        <h2 className="text-2xl sm:text-3xl font-extrabold text-slate-900 text-center">How it works</h2>
        <ol className="mt-10 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {STEPS.map((s, i) => (
            <li key={s.title} className="glass-panel rounded-2xl border border-gray-200 p-6">
              <span className="w-8 h-8 rounded-full bg-brand-600 text-white text-sm font-black flex items-center justify-center">{i + 1}</span>
              <h3 className="mt-4 text-sm font-bold text-slate-900">{s.title}</h3>
              <p className="mt-1 text-xs text-slate-500 leading-relaxed">{s.text}</p>
            </li>
          ))}
        </ol>
      </section>

      {/* Two ways to sell */}
      <section className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="glass-panel rounded-2xl border border-gray-200 p-7">
          <LayoutDashboard className="w-6 h-6 text-merchant-600" />
          <h3 className="mt-3 text-lg font-bold text-slate-900">Partner dashboard</h3>
          <p className="mt-1 text-xs text-slate-500 leading-relaxed">
            Issue an eSIM for any customer in a few clicks, track every order, see your commission and download monthly statements.
          </p>
          <p className="mt-4 flex items-center gap-2 text-xs text-slate-600"><Send className="w-3.5 h-3.5 text-brand-600" /> No integration needed</p>
        </div>
        <div className="glass-panel rounded-2xl border border-gray-200 p-7">
          <Code2 className="w-6 h-6 text-merchant-600" />
          <h3 className="mt-3 text-lg font-bold text-slate-900">Partner API</h3>
          <p className="mt-1 text-xs text-slate-500 leading-relaxed">
            Sell from your own site or booking engine. Browse the catalogue, place orders and receive delivery updates by webhook.
          </p>
          <p className="mt-4 flex items-center gap-2 text-xs text-slate-600"><ShieldCheck className="w-3.5 h-3.5 text-emerald-600" /> Signed webhooks and idempotent orders</p>
        </div>
      </section>

      {/* FAQ */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8">
        <h2 className="text-2xl sm:text-3xl font-extrabold text-slate-900 text-center">Questions</h2>
        <div className="mt-8 space-y-3">
          {FAQ.map((f) => (
            <details key={f.q} className="glass-panel rounded-2xl border border-gray-200 p-5 group">
              <summary className="cursor-pointer list-none flex items-center justify-between text-sm font-bold text-slate-900">
                {f.q}
                <span className="text-slate-400 group-open:rotate-45 transition-transform text-lg leading-none">+</span>
              </summary>
              <p className="mt-2 text-xs text-slate-500 leading-relaxed">{f.a}</p>
            </details>
          ))}
        </div>
      </section>

      {/* Final CTA */}
      <section className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="rounded-3xl bg-slate-900 text-white p-8 sm:p-12 flex flex-col md:flex-row md:items-center justify-between gap-6">
          <div>
            <h2 className="text-2xl font-extrabold">Ready to add eSIMs to what you sell?</h2>
            <p className="mt-2 text-sm text-white/70">Applications take two minutes. We&apos;ll review yours and set up your account.</p>
          </div>
          <div className="shrink-0">
            <PartnerCta guestSecondary={{ label: "Create an account", href: "/auth/register" }} />
          </div>
        </div>
      </section>
    </div>
  );
}
