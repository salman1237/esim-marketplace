"use client";

import React, { useCallback, useEffect, useState } from "react";
import { Radar, RefreshCw, Search, Smartphone } from "lucide-react";
import { api } from "@/lib/api";
import EsimLiveStatus from "@/components/admin/EsimLiveStatus";

type Row = {
  order_id: string;
  order_no: string;
  order_status: string;
  purchased_at: string;
  customer_name: string;
  customer_email: string;
  customer_phone: string | null;
  country: string;
  product: string;
  esim_id: string | null;
  iccid: string | null;
  esim_status: string | null;
  data_used_mb: string | null;
  is_installed: boolean | null;
  activated_at: string | null;
  expires_at: string | null;
  usage_fetched_at: string | null;
};

function getToken() {
  try {
    return localStorage.getItem("esim_token");
  } catch {
    return null;
  }
}

const STATUS_STYLE: Record<string, string> = {
  COMPLETED: "bg-emerald-50 text-emerald-700",
  PROCESSING: "bg-amber-50 text-amber-700",
  PENDING: "bg-amber-50 text-amber-700",
  FAILED: "bg-rose-50 text-rose-700",
  CANCELLED: "bg-gray-100 text-slate-600",
};

export default function EsimQuickTrack() {
  const [query, setQuery] = useState("");
  const [rows, setRows] = useState<Row[] | null>(null);
  const [counts, setCounts] = useState<{ total_esims: number; installed: number; never_installed: number } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openEsim, setOpenEsim] = useState<Row | null>(null);

  const run = useCallback(async (term: string) => {
    const token = getToken();
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (term.trim()) params.append("query", term.trim());
      const res = await api.searchEsims(token, params.toString());
      setRows(res.items);
    } catch (err: any) {
      setError(err.message || "Search failed");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const token = getToken();
    if (!token) return;
    api.getEsimCounts(token).then(setCounts).catch(() => undefined);
    run("");
  }, [run]);

  return (
    <div className="glass-panel rounded-2xl p-6 border border-gray-200">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h3 className="text-base font-bold text-slate-900 flex items-center gap-2">
            <Radar className="w-4 h-4 text-admin-600" /> Quick track an eSIM
          </h3>
          <p className="text-xs text-slate-500 mt-1 max-w-2xl">
            Search by ICCID (even the last few digits), order number, customer email, phone or name.
          </p>
        </div>
        {counts && (
          <div className="flex gap-2 text-center">
            <div className="rounded-xl border border-gray-200 bg-gray-50 px-3 py-2">
              <div className="text-sm font-black text-slate-900">{counts.total_esims}</div>
              <div className="text-[10px] text-slate-500 uppercase tracking-wider">eSIMs</div>
            </div>
            <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2">
              <div className="text-sm font-black text-emerald-800">{counts.installed}</div>
              <div className="text-[10px] text-emerald-700 uppercase tracking-wider">Installed</div>
            </div>
            <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2">
              <div className="text-sm font-black text-amber-800">{counts.never_installed}</div>
              <div className="text-[10px] text-amber-700 uppercase tracking-wider">Not installed</div>
            </div>
          </div>
        )}
      </div>

      <div className="mt-4 flex gap-2">
        <div className="relative flex-1">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && run(query)}
            placeholder="ICCID, order no, email, phone or name…"
            className="w-full bg-white border border-gray-300 rounded-xl ps-10 pe-3 py-2.5 text-xs text-slate-900"
          />
        </div>
        <button
          onClick={() => run(query)}
          disabled={loading}
          className="bg-admin-600 hover:bg-admin-500 text-white text-xs font-bold px-5 py-2.5 rounded-xl flex items-center gap-1.5 disabled:opacity-60"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
          {loading ? "Searching…" : "Search"}
        </button>
      </div>

      {error && <p className="mt-3 text-xs text-rose-600">{error}</p>}

      {!rows ? (
        <div className="mt-4 h-24 rounded-xl bg-gray-50 animate-pulse" />
      ) : rows.length === 0 ? (
        <p className="mt-4 text-sm text-slate-600">No eSIM or order matches that.</p>
      ) : (
        <div className="mt-4 overflow-x-auto max-h-[440px] overflow-y-auto">
          <table className="w-full text-start text-xs">
            <thead className="text-slate-500 border-b border-gray-200 sticky top-0 bg-white">
              <tr>
                <th className="py-2">Status</th>
                <th className="py-2">Customer</th>
                <th className="py-2">Package</th>
                <th className="py-2">ICCID</th>
                <th className="py-2">Usage</th>
                <th className="py-2">Expires</th>
                <th className="py-2"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {rows.map((r) => (
                <tr key={r.order_id}>
                  <td className="py-2.5">
                    <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${STATUS_STYLE[r.order_status] || "bg-gray-100 text-slate-600"}`}>
                      {r.order_status}
                    </span>
                    <div className="text-[10px] text-slate-400 mt-0.5 whitespace-nowrap">{r.purchased_at}</div>
                  </td>
                  <td className="py-2.5 text-slate-700">
                    <div className="font-semibold">{r.customer_name}</div>
                    <div className="text-[10px] text-slate-500">{r.customer_email}</div>
                    {r.customer_phone && <div className="text-[10px] text-slate-500">{r.customer_phone}</div>}
                  </td>
                  <td className="py-2.5 text-slate-700">{r.country} · {r.product}</td>
                  <td className="py-2.5 font-mono text-[11px]">
                    {r.iccid ? (
                      <button onClick={() => navigator.clipboard?.writeText(r.iccid!)} className="text-admin-600 hover:underline" title="Copy ICCID">
                        {r.iccid}
                      </button>
                    ) : (
                      <span className="text-slate-400">no eSIM</span>
                    )}
                  </td>
                  <td className="py-2.5 text-slate-600 whitespace-nowrap">
                    {r.data_used_mb !== null ? (
                      <>
                        {Number(r.data_used_mb).toFixed(1)} MB
                        <div className="text-[10px] text-slate-400">{r.is_installed ? "installed" : "not installed"}</div>
                      </>
                    ) : (
                      <span className="text-slate-400">—</span>
                    )}
                  </td>
                  <td className="py-2.5 text-slate-500 whitespace-nowrap">{r.expires_at || "—"}</td>
                  <td className="py-2.5">
                    {r.esim_id && (
                      <button
                        onClick={() => setOpenEsim(r)}
                        className="flex items-center gap-1 text-[11px] font-bold px-2.5 py-1 rounded-lg bg-gray-100 hover:bg-gray-200 text-slate-700"
                      >
                        <Smartphone className="w-3 h-3" /> Live
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {openEsim?.esim_id && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-sm p-4" onClick={() => setOpenEsim(null)}>
          <div className="glass-panel rounded-2xl max-w-2xl w-full p-6 border border-gray-300 shadow-2xl max-h-[85vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h4 className="text-sm font-bold text-slate-900">
                {openEsim.customer_name} — {openEsim.order_no}
              </h4>
              <button onClick={() => setOpenEsim(null)} className="text-slate-500 hover:text-slate-900 text-xs font-bold">Close</button>
            </div>
            <EsimLiveStatus esimId={openEsim.esim_id} />
          </div>
        </div>
      )}
    </div>
  );
}
