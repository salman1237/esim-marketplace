"use client";

import React from "react";
import Link from "next/link";
import { AlertTriangle, ArrowRight, Code2, Coins, Percent, TrendingUp, Wallet, Send } from "lucide-react";
import { MerchantTab, Panel, SourceBadge, StatusBadge, dataLabel, formatDateTime } from "./shared";

// Below this, a typical order will fail with "insufficient balance".
const LOW_BALANCE = 10;

type Props = {
  overview: any | null;
  formatPrice: (amountUsd: number) => string;
  onNavigate: (tab: MerchantTab) => void;
};

function StatCard({ icon: Icon, label, value, hint, action }: { icon: any; label: string; value: string; hint?: string; action?: React.ReactNode }) {
  return (
    <div className="glass-panel rounded-2xl p-5 border border-gray-200 flex flex-col">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">{label}</span>
        <Icon className="w-4 h-4 text-merchant-600" />
      </div>
      <div className="text-2xl font-black text-slate-900 font-mono mt-2">{value}</div>
      {hint && <div className="text-[11px] text-slate-500 mt-1">{hint}</div>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}

export default function OverviewTab({ overview, formatPrice, onNavigate }: Props) {
  if (!overview) {
    return (
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="h-32 rounded-2xl bg-gray-100 animate-pulse" />
        ))}
      </div>
    );
  }

  const { wallets, stats, commission, api: apiStatus, recent_orders: recentOrders } = overview;
  const walletBalance = Number(wallets.wallet_balance);
  const last30 = stats.last_30_days;
  const allTime = stats.all_time;
  const nextTier = commission.next_tier;
  const tierProgress = nextTier
    ? Math.min(100, (Number(commission.completed_volume) / Number(nextTier.min_volume)) * 100)
    : 100;

  return (
    <div className="space-y-6">
      {walletBalance < LOW_BALANCE && (
        <div className="flex items-start gap-3 p-4 rounded-xl bg-amber-50 border border-amber-200 text-xs text-amber-800">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
          <div className="flex-1">
            <strong>Low wallet balance.</strong> Every order — including Partner API orders — is paid from this balance and
            fails with &ldquo;insufficient balance&rdquo; when it can&apos;t cover the eSIM.
          </div>
          <Link href="/wallet" className="font-bold underline whitespace-nowrap">Top up</Link>
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          icon={Wallet}
          label="Wallet balance"
          value={formatPrice(walletBalance)}
          hint="Pays for every eSIM you sell"
          action={<Link href="/wallet" className="text-xs font-bold text-brand-600 hover:text-brand-700">Top up →</Link>}
        />
        <StatCard
          icon={Coins}
          label="Commission balance"
          value={formatPrice(Number(wallets.commission_balance))}
          hint="Earned on completed orders"
          action={
            <button onClick={() => onNavigate("commission")} className="text-xs font-bold text-merchant-600 hover:text-merchant-700">
              Move to wallet →
            </button>
          }
        />
        <StatCard
          icon={TrendingUp}
          label="Sales · 30 days"
          value={formatPrice(Number(last30.volume))}
          hint={`${last30.completed} completed of ${last30.orders} orders`}
        />
        <StatCard
          icon={Percent}
          label="Commission · 30 days"
          value={formatPrice(Number(last30.commission))}
          hint={`Current rate ${Number(commission.effective_rate_pct)}%`}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Panel title="Performance" description="Across all your reseller orders">
          <dl className="space-y-2.5 text-xs">
            <div className="flex justify-between"><dt className="text-slate-500">Success rate</dt><dd className="font-bold text-slate-900">{allTime.success_rate_pct === null ? "—" : `${allTime.success_rate_pct}%`}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">Setting up now</dt><dd className="font-bold text-slate-900">{allTime.in_progress}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">Failed (auto-refunded)</dt><dd className="font-bold text-slate-900">{allTime.failed}</dd></div>
            <div className="flex justify-between border-t border-gray-100 pt-2.5"><dt className="text-slate-500">All-time sales</dt><dd className="font-bold text-slate-900">{formatPrice(Number(allTime.volume))}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">All-time orders</dt><dd className="font-bold text-slate-900">{allTime.orders}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">All-time commission</dt><dd className="font-bold text-merchant-600">{formatPrice(Number(allTime.commission))}</dd></div>
          </dl>
        </Panel>

        <Panel title="Commission rate">
          <div className="text-3xl font-black text-merchant-600 font-mono">{Number(commission.effective_rate_pct)}%</div>
          <p className="text-[11px] text-slate-500 mt-1">of every completed order, credited to your commission balance</p>
          {nextTier ? (
            <div className="mt-4">
              <div className="h-2 rounded-full bg-gray-100 overflow-hidden">
                <div className="h-full bg-merchant-500 rounded-full" style={{ width: `${tierProgress}%` }} />
              </div>
              <p className="text-[11px] text-slate-600 mt-2">
                Sell <strong>{formatPrice(Number(nextTier.volume_remaining))}</strong> more in completed orders to earn{" "}
                <strong>{Number(nextTier.rate_pct)}%</strong>.
              </p>
            </div>
          ) : (
            <p className="text-[11px] text-slate-600 mt-4">You&apos;re on the best rate currently available.</p>
          )}
        </Panel>

        <Panel title="Partner API">
          <dl className="space-y-2.5 text-xs">
            <div className="flex justify-between"><dt className="text-slate-500">API key</dt><dd className={`font-bold ${apiStatus.key_active ? "text-emerald-600" : "text-slate-500"}`}>{apiStatus.key_active ? `Active · ${apiStatus.key_prefix}…` : "Not issued"}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">Last used</dt><dd className="font-bold text-slate-900">{apiStatus.key_last_used_at ? formatDateTime(apiStatus.key_last_used_at) : "—"}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">Webhook</dt><dd className={`font-bold ${apiStatus.webhook_configured ? "text-emerald-600" : "text-slate-500"}`}>{apiStatus.webhook_configured ? "Configured" : "Not set"}</dd></div>
          </dl>
          <button onClick={() => onNavigate("api")} className="mt-4 w-full py-2 rounded-xl border border-gray-200 bg-white hover:bg-gray-50 text-xs font-bold text-slate-700 flex items-center justify-center gap-1.5">
            <Code2 className="w-3.5 h-3.5" /> Manage API &amp; webhooks
          </button>
        </Panel>
      </div>

      <Panel
        title="Recent orders"
        actions={
          recentOrders.length > 0 && (
            <button onClick={() => onNavigate("orders")} className="text-xs font-bold text-brand-600 hover:text-brand-700 flex items-center gap-1">
              View all <ArrowRight className="w-3.5 h-3.5" />
            </button>
          )
        }
      >
        {recentOrders.length === 0 ? (
          <div className="text-center py-8">
            <p className="text-xs text-slate-500 mb-3">No orders yet — issue your first eSIM to a customer.</p>
            <button onClick={() => onNavigate("provision")} className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-brand-600 hover:bg-brand-500 text-white text-xs font-bold">
              <Send className="w-3.5 h-3.5" /> Buy for a customer
            </button>
          </div>
        ) : (
          <ul className="divide-y divide-gray-100">
            {recentOrders.map((o: any) => (
              <li key={o.order_id} className="py-2.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                <span className="font-mono text-brand-600">{o.order_no}</span>
                <SourceBadge source={o.source} />
                <span className="text-slate-700 flex-1 min-w-[10rem]">
                  {o.product.title} · {dataLabel(o.product)} · {o.product.validity_days}d
                </span>
                <span className="font-bold text-slate-900">{formatPrice(Number(o.amount))}</span>
                <StatusBadge status={o.status} />
                <span className="text-slate-400 w-full sm:w-auto">{formatDateTime(o.created_at)}</span>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}
