"use client";

import React, { useCallback, useEffect, useState } from "react";
import { Database, RefreshCw, Signal, Smartphone, WifiOff } from "lucide-react";
import { api } from "@/lib/api";

// Support panel: the same telemetry the customer sees, so nobody debugs
// against different numbers than the person on the phone is looking at.
// Fetched on demand — an order list must not fire a supplier call per row.
export default function EsimLiveStatus({ esimId }: { esimId: string }) {
  const [data, setData] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (force = false) => {
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    const fn = force ? api.refreshEsimStatus : api.getEsimStatus;
    setData(await fn(token, esimId));
  }, [esimId]);

  useEffect(() => {
    load()
      .catch((err) => setError(err.message || "Couldn't load live status"))
      .finally(() => setLoading(false));
  }, [load]);

  const refresh = async () => {
    setRefreshing(true);
    setError(null);
    try {
      await load(true);
    } catch (err: any) {
      setError(err.message || "Couldn't refresh");
    } finally {
      setRefreshing(false);
    }
  };

  if (loading) return <div className="h-20 rounded-xl bg-gray-50 animate-pulse" />;
  if (!data) return <p className="text-[11px] text-rose-600">{error || "No live status available."}</p>;

  const active = data.status.is_activated;
  const pct = data.usage.used_pct;

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <h4 className="text-xs font-bold text-slate-900 flex items-center gap-1.5">
          <Signal className={`w-3.5 h-3.5 ${active ? "text-emerald-600" : "text-slate-400"}`} /> Live carrier status
        </h4>
        <button
          onClick={refresh}
          disabled={refreshing}
          className="inline-flex items-center gap-1 text-[11px] font-semibold text-brand-600 hover:text-brand-700 disabled:opacity-60"
        >
          <RefreshCw className={`w-3 h-3 ${refreshing ? "animate-spin" : ""}`} /> {refreshing ? "Checking…" : "Refresh"}
        </button>
      </div>

      {data.telemetry.error && (
        <p className="mb-3 text-[11px] text-amber-700 flex items-start gap-1.5">
          <WifiOff className="w-3 h-3 shrink-0 mt-0.5" />
          Supplier unreachable — showing the last known figures. ({data.telemetry.error})
        </p>
      )}

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
        <div>
          <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">Status</div>
          <div className={`font-bold ${active ? "text-emerald-600" : "text-slate-700"}`}>{data.status.label}</div>
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold flex items-center gap-1">
            <Database className="w-3 h-3" /> Used
          </div>
          <div className="font-bold text-slate-900">{data.usage.formatted || "0 MB"}</div>
          {!data.usage.is_unlimited && pct !== null && (
            <div className="text-[10px] text-slate-500">{pct}% of plan</div>
          )}
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold flex items-center gap-1">
            <Smartphone className="w-3 h-3" /> Handset
          </div>
          <div className="text-slate-700">
            {data.status.is_installed ? (data.status.device_model || "Installed") : "Not installed"}
          </div>
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">Expires</div>
          <div className="text-slate-700">
            {data.validity.expires_at
              ? new Date(data.validity.expires_at).toLocaleDateString()
              : `On install +${data.validity.days}d`}
          </div>
        </div>
      </div>

      {data.history.length > 0 && (
        <div className="mt-3 pt-3 border-t border-gray-100">
          <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-1.5">Carrier events</div>
          <ul className="space-y-1">
            {data.history.slice(0, 5).map((h: any, i: number) => (
              <li key={i} className="text-[11px] text-slate-600 flex flex-wrap gap-x-2">
                <span className="font-semibold text-slate-800">{h.event_name}</span>
                <span className="text-slate-400">{h.date}</span>
                <span className="text-slate-500">{h.status}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {data.daily_breakdown.length > 0 && (
        <div className="mt-3 pt-3 border-t border-gray-100">
          <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-1.5">Where the data went</div>
          <ul className="space-y-1">
            {data.daily_breakdown.slice(0, 5).map((d: any, i: number) => (
              <li key={i} className="text-[11px] text-slate-600">
                {d.enus} · {d.mnoname} · {d.usage ? `${(Number(d.usage) / 1024 / 1024).toFixed(2)} MB` : "—"}
              </li>
            ))}
          </ul>
        </div>
      )}

      {error && <p className="mt-2 text-[11px] text-rose-600">{error}</p>}
    </div>
  );
}
