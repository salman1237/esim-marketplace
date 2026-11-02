"use client";

import React, { useState } from "react";
import {
  Activity, AlertTriangle, CheckCircle2, Check, Clock, Copy, Database,
  RefreshCw, Signal, Smartphone, WifiOff,
} from "lucide-react";
import { esimInstallLinks } from "@/lib/esimInstall";
import { formatDateTimeZoned, formatDayLabel } from "@/lib/datetime";
import EsimQr from "@/components/EsimQr";

export type EsimStatus = {
  esim_id: string;
  order_no: string;
  purchased_at: string;
  product: { title: string; validity_days: number; is_unlimited: boolean; data_amount_gb: string | null };
  iccid: string | null;
  lpa_string: string | null;
  qr_code_data: string | null;
  smdp_address: string | null;
  matching_id: string | null;
  status: { label: string; code: number | null; is_installed: boolean; is_activated: boolean; device_model: string | null };
  usage: {
    used_mb: string; used_bytes: number; formatted: string | null;
    allowance_mb: string | null; remaining_mb: string | null; remaining_formatted: string | null;
    used_pct: number | null; is_unlimited: boolean;
  };
  validity: { days: number; activated_at: string | null; expires_at: string | null; note: string | null };
  share_url: string | null;
  history: { event_name?: string; date?: string; status?: string }[];
  daily_breakdown: { usageDate?: string; enus?: string; mnoname?: string; usage?: string }[];
  telemetry: { fetched_at: string | null; error: string | null; available: boolean };
};

// Bangladesh time, always — see lib/datetime. A traveller reading this
// page has a phone that has just switched to a foreign timezone, and an
// expiry that quietly re-renders in local time cannot be compared with
// the receipt or the support reply that quoted it.
export const fmtDate = (v?: string | null) => formatDateTimeZoned(v);
const mbLabel = (v?: string | null) => (v === null || v === undefined ? "—" : `${Number(v).toFixed(2)} MB`);

function dayLabel(yyyymmdd?: string) {
  if (!yyyymmdd || yyyymmdd.length !== 8) return yyyymmdd || "—";
  return formatDayLabel(`${yyyymmdd.slice(0, 4)}-${yyyymmdd.slice(4, 6)}-${yyyymmdd.slice(6, 8)}`);
}

export function CopyRow({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div>
      <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 mb-1">{label}</div>
      <button
        type="button"
        onClick={() => {
          navigator.clipboard?.writeText(value).then(() => {
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          }).catch(() => {});
        }}
        className="w-full flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-3 py-2 text-start hover:border-brand-500 transition-colors"
      >
        <span className="flex-1 min-w-0 font-mono text-xs text-slate-900 break-all">{value}</span>
        {copied ? <Check className="w-3.5 h-3.5 text-emerald-600 shrink-0" /> : <Copy className="w-3.5 h-3.5 text-slate-400 shrink-0" />}
      </button>
    </div>
  );
}

// Shared by the signed-in owner's page and the public tracking link, so a
// customer forwarding their link shows exactly what they were looking at.
export default function EsimStatusView({
  data, refreshing, onRefresh, actions,
}: {
  data: EsimStatus;
  refreshing?: boolean;
  onRefresh?: () => void;
  actions?: React.ReactNode;
}) {
  const install = esimInstallLinks(data.lpa_string);
  const active = data.status.is_activated;
  const pct = data.usage.used_pct;

  return (
    <>
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl sm:text-3xl font-extrabold text-slate-900">{data.product.title}</h1>
          <p className="text-xs text-slate-500 mt-1 font-mono break-all">
            {data.order_no}
            {data.iccid ? <> · ICCID {data.iccid}</> : null}
          </p>
        </div>
        <div className="flex gap-2 shrink-0">
          {onRefresh && (
            <button
              onClick={onRefresh}
              disabled={refreshing}
              className="inline-flex items-center gap-1.5 bg-white hover:bg-gray-50 border border-gray-300 text-slate-700 text-xs font-bold px-3 py-2 rounded-xl disabled:opacity-60"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? "animate-spin" : ""}`} /> {refreshing ? "Checking…" : "Refresh"}
            </button>
          )}
          {actions}
        </div>
      </div>

      {/* When the carrier can't be reached we say so rather than showing zeros
          as though they were facts. */}
      {data.telemetry.error && (
        <div className="mb-6 p-4 rounded-xl border border-amber-200 bg-amber-50 text-xs text-amber-800 flex items-start gap-2">
          <WifiOff className="w-4 h-4 shrink-0 mt-0.5" />
          <span>
            Live data from the carrier is temporarily unavailable
            {data.telemetry.fetched_at ? <> — showing what we last saw at {fmtDate(data.telemetry.fetched_at)}</> : null}.
            Your install details below are always available.
          </span>
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
        <div className="glass-panel rounded-2xl p-5 border border-gray-200">
          <div className="flex items-center justify-between text-[11px] font-semibold uppercase tracking-wider text-slate-500">
            Data used <Database className="w-4 h-4 text-brand-600" />
          </div>
          <div className="text-2xl font-black text-slate-900 mt-1">{data.usage.formatted || "0 MB"}</div>
          {data.usage.is_unlimited ? (
            <div className="text-[11px] text-slate-500 mt-1">Unlimited plan</div>
          ) : (
            <>
              <div className="h-1.5 mt-2 rounded-full bg-gray-100 overflow-hidden">
                <div
                  className={`h-full ${pct !== null && pct >= 90 ? "bg-rose-500" : pct !== null && pct >= 70 ? "bg-amber-500" : "bg-emerald-500"}`}
                  style={{ width: `${Math.min(100, pct ?? 0)}%` }}
                />
              </div>
              <div className="text-[11px] text-slate-500 mt-1">
                {data.usage.remaining_formatted} left of {mbLabel(data.usage.allowance_mb)}
              </div>
            </>
          )}
        </div>

        <div className="glass-panel rounded-2xl p-5 border border-gray-200">
          <div className="flex items-center justify-between text-[11px] font-semibold uppercase tracking-wider text-slate-500">
            SIM status <Signal className={`w-4 h-4 ${active ? "text-emerald-600" : "text-slate-400"}`} />
          </div>
          <div className={`text-2xl font-black mt-1 ${active ? "text-emerald-600" : "text-slate-900"}`}>
            {data.status.label}
          </div>
          <div className="text-[11px] text-slate-500 mt-1 flex items-center gap-1">
            {data.status.is_installed ? (
              <>
                <Smartphone className="w-3 h-3" />
                {data.status.device_model && data.status.device_model !== "Not Yet Installed"
                  ? data.status.device_model
                  : "Installed on a device"}
              </>
            ) : (
              "Not installed on a phone yet"
            )}
          </div>
        </div>

        <div className="glass-panel rounded-2xl p-5 border border-gray-200">
          <div className="flex items-center justify-between text-[11px] font-semibold uppercase tracking-wider text-slate-500">
            Validity <Clock className="w-4 h-4 text-brand-600" />
          </div>
          <div className="text-2xl font-black text-slate-900 mt-1">{data.validity.days} days</div>
          <div className="text-[11px] text-slate-500 mt-1">
            {data.validity.expires_at ? `Expires ${fmtDate(data.validity.expires_at)}` : "Starts when you install it"}
          </div>
        </div>
      </div>

      {/* The single most misunderstood thing about an eSIM. */}
      {data.validity.note && (
        <div className="mb-6 p-4 rounded-xl border border-brand-200 bg-brand-50 text-xs text-brand-900 flex items-start gap-2">
          <Activity className="w-4 h-4 shrink-0 mt-0.5 text-brand-600" />
          <span>{data.validity.note} Buy ahead of your trip and install it when you land — nothing is used up in the meantime.</span>
        </div>
      )}

      <div className="glass-panel rounded-2xl p-6 border border-gray-200 mb-6">
        <h2 className="text-base font-bold text-slate-900 mb-1">
          {data.status.is_installed ? "Install on another device" : "Install this eSIM"}
        </h2>
        <p className="text-xs text-slate-500 mb-5">
          Use 1-tap installation on the phone that will use the eSIM, or scan the QR code from another device.
        </p>

        <div className="flex flex-wrap gap-2 mb-5">
          {install.ios && (
            <a href={install.ios} className="bg-slate-900 hover:bg-slate-800 text-white text-xs font-bold px-4 py-2.5 rounded-xl">
              Set up on iPhone
            </a>
          )}
          {install.android && (
            <a href={install.android} className="bg-emerald-500 hover:bg-emerald-400 text-slate-900 text-xs font-bold px-4 py-2.5 rounded-xl">
              Set up on Android
            </a>
          )}
        </div>

        <div className="grid grid-cols-1 md:grid-cols-[auto_1fr] gap-6 items-start">
          {data.qr_code_data && (
            <div className="bg-white border border-gray-200 rounded-xl p-4 text-center">
              <EsimQr value={data.qr_code_data} size={160} />
              <p className="text-[10px] text-slate-500 mt-2">Scan with the phone&apos;s camera</p>
            </div>
          )}
          <div className="space-y-3 min-w-0">
            {data.smdp_address && <CopyRow label="SM-DP+ address" value={data.smdp_address} />}
            {data.matching_id && <CopyRow label="Activation code (matching ID)" value={data.matching_id} />}
            {data.lpa_string && <CopyRow label="Full LPA activation string" value={data.lpa_string} />}
          </div>
        </div>
      </div>

      <div className="glass-panel rounded-2xl p-6 border border-gray-200 mb-6">
        <h2 className="text-base font-bold text-slate-900 mb-4">eSIM details</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-start text-xs">
            <tbody className="divide-y divide-gray-100">
              {[
                ["Plan", data.product.title],
                ["Data", data.product.is_unlimited ? "Unlimited" : `${data.product.data_amount_gb} GB`],
                ["Validity", `${data.validity.days} days`],
                ["Order reference", data.order_no],
                ["ICCID", data.iccid || "—"],
                ["Purchased", fmtDate(data.purchased_at)],
                ["First activated", data.validity.activated_at ? fmtDate(data.validity.activated_at) : "Not yet"],
                ["Expires", data.validity.expires_at ? fmtDate(data.validity.expires_at) : `On install + ${data.validity.days} days`],
                ["Detected handset", data.status.device_model && data.status.is_installed ? data.status.device_model : "—"],
              ].map(([label, value]) => (
                <tr key={String(label)}>
                  <td className="py-2.5 pe-4 text-slate-500 whitespace-nowrap">{label}</td>
                  <td className="py-2.5 text-slate-900 font-medium break-all">{value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {data.daily_breakdown.length > 0 && (
        <div className="glass-panel rounded-2xl p-6 border border-gray-200 mb-6">
          <h2 className="text-base font-bold text-slate-900 mb-4">Daily usage</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-start text-xs">
              <thead className="text-slate-500 border-b border-gray-200">
                <tr>
                  <th className="py-2 pe-3 text-start">Day</th>
                  <th className="py-2 pe-3 text-start">Where</th>
                  <th className="py-2 pe-3 text-start">Network</th>
                  <th className="py-2 text-end">Used</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {data.daily_breakdown.map((d, i) => (
                  <tr key={i}>
                    <td className="py-2.5 pe-3 text-slate-700">{dayLabel(d.usageDate)}</td>
                    <td className="py-2.5 pe-3 text-slate-700">{d.enus || "—"}</td>
                    <td className="py-2.5 pe-3 text-slate-500">{d.mnoname || "—"}</td>
                    <td className="py-2.5 text-end font-mono text-slate-900">
                      {d.usage ? `${(Number(d.usage) / 1024 / 1024).toFixed(2)} MB` : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {data.history.length > 0 && (
        <div className="glass-panel rounded-2xl p-6 border border-gray-200">
          <h2 className="text-base font-bold text-slate-900 mb-4">Installation history</h2>
          <ol className="space-y-3">
            {data.history.map((h, i) => (
              <li key={i} className="flex items-start gap-3">
                <span className="w-6 h-6 rounded-full bg-emerald-50 text-emerald-600 flex items-center justify-center shrink-0 mt-0.5">
                  {String(h.status || "").toLowerCase().includes("success")
                    ? <CheckCircle2 className="w-3.5 h-3.5" />
                    : <AlertTriangle className="w-3.5 h-3.5 text-amber-600" />}
                </span>
                <div className="min-w-0">
                  <div className="text-sm font-semibold text-slate-900">{h.event_name || "Carrier event"}</div>
                  <div className="text-[11px] text-slate-500">{fmtDate(h.date)} · {h.status}</div>
                </div>
              </li>
            ))}
          </ol>
        </div>
      )}

      {data.telemetry.fetched_at && !data.telemetry.error && (
        <p className="mt-6 text-[11px] text-slate-400">
          Live figures from the carrier, last checked {fmtDate(data.telemetry.fetched_at)}.
        </p>
      )}
    </>
  );
}
