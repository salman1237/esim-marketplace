"use client";

import React, { useCallback, useEffect, useState } from "react";
import { ArrowDown, ArrowUp, Download, FileSpreadsheet, FileText, Search, Wallet } from "lucide-react";
import { api } from "@/lib/api";
import { saveBlob } from "@/components/finance/StatementView";

type Row = {
  user_id: string;
  customer_name: string;
  email: string;
  phone: string | null;
  role: string;
  status: string;
  default_balance: string;
  reward_balance: string;
  commission_balance: string;
  total_balance: string;
  last_activity: string | null;
  created_at: string | null;
};

type Summary = {
  wallet_holders: number;
  total_default_eur: string;
  total_reward_eur: string;
  total_commission_eur: string;
  total_all_eur: string;
};

type SortKey = "total" | "default" | "reward" | "commission" | "name" | "email" | "last_activity";

function getToken() {
  try {
    return localStorage.getItem("esim_token");
  } catch {
    return null;
  }
}

export default function WalletReport() {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [search, setSearch] = useState("");
  const [minBalance, setMinBalance] = useState("");
  const [sort, setSort] = useState<SortKey>("total");
  const [descending, setDescending] = useState(true);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const params = useCallback(() => {
    const p = new URLSearchParams();
    if (search.trim()) p.append("search", search.trim());
    if (minBalance.trim()) p.append("min_balance", minBalance.trim());
    p.append("sort", sort);
    p.append("descending", String(descending));
    return p;
  }, [search, minBalance, sort, descending]);

  const load = useCallback(async () => {
    const token = getToken();
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      const res = await api.getWalletReport(token, params().toString());
      setRows(res.items);
      setSummary(res.summary);
    } catch (err: any) {
      setError(err.message || "Couldn't load wallet balances");
    } finally {
      setLoading(false);
    }
  }, [params]);

  useEffect(() => {
    load();
  }, [sort, descending]); // eslint-disable-line react-hooks/exhaustive-deps

  const download = async (fmt: "csv" | "xlsx" | "pdf") => {
    const token = getToken();
    if (!token) return;
    setExporting(fmt);
    try {
      const p = params();
      p.append("fmt", fmt);
      const blob = await api.downloadAuthed(token, `/api/v1/admin/reports/wallets/export?${p.toString()}`);
      saveBlob(blob, `wallet-balances-${new Date().toISOString().slice(0, 10)}.${fmt}`);
    } catch (err: any) {
      setError(err.message || "Export failed");
    } finally {
      setExporting(null);
    }
  };

  const sortBy = (key: SortKey) => {
    if (sort === key) setDescending((d) => !d);
    else {
      setSort(key);
      setDescending(true);
    }
  };

  const Th = ({ label, sortKey }: { label: string; sortKey?: SortKey }) => (
    <th className="py-2">
      {sortKey ? (
        <button onClick={() => sortBy(sortKey)} className="flex items-center gap-1 hover:text-slate-900">
          {label}
          {sort === sortKey && (descending ? <ArrowDown className="w-3 h-3" /> : <ArrowUp className="w-3 h-3" />)}
        </button>
      ) : label}
    </th>
  );

  return (
    <div className="glass-panel rounded-2xl p-6 border border-gray-200">
      <h3 className="text-base font-bold text-slate-900 flex items-center gap-2">
        <Wallet className="w-4 h-4 text-admin-600" /> Customer wallet balances
      </h3>
      <p className="text-xs text-slate-500 mt-1 max-w-3xl">
        Cash, reward credit and commission are shown separately — they are not interchangeable. Only the cash column
        is money that could be asked for back; reward credit can be spent but never withdrawn.
      </p>

      {summary && (
        <div className="mt-4 grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3">
            <div className="text-[10px] font-bold uppercase tracking-wider text-emerald-700">Cash held</div>
            <div className="text-xl font-black text-emerald-800">€{summary.total_default_eur}</div>
          </div>
          <div className="rounded-xl border border-violet-200 bg-violet-50 px-4 py-3">
            <div className="text-[10px] font-bold uppercase tracking-wider text-violet-700">Reward credit</div>
            <div className="text-xl font-black text-violet-800">€{summary.total_reward_eur}</div>
          </div>
          <div className="rounded-xl border border-sky-200 bg-sky-50 px-4 py-3">
            <div className="text-[10px] font-bold uppercase tracking-wider text-sky-700">Commission owed</div>
            <div className="text-xl font-black text-sky-800">€{summary.total_commission_eur}</div>
          </div>
          <div className="rounded-xl border border-gray-200 bg-gray-50 px-4 py-3">
            <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Wallet holders</div>
            <div className="text-xl font-black text-slate-900">{summary.wallet_holders}</div>
          </div>
        </div>
      )}

      <div className="mt-4 flex flex-wrap gap-2 items-end">
        <div className="flex-1 min-w-[200px]">
          <label className="text-[11px] font-bold text-slate-600 block mb-1">Search</label>
          <div className="relative">
            <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && load()}
              placeholder="Name, email or phone…"
              className="w-full bg-white border border-gray-300 rounded-lg ps-9 pe-3 py-2 text-xs text-slate-900"
            />
          </div>
        </div>
        <div>
          <label className="text-[11px] font-bold text-slate-600 block mb-1">Min balance (€)</label>
          <input
            type="number" min="0" step="0.01" value={minBalance}
            onChange={(e) => setMinBalance(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && load()}
            className="w-32 bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900"
          />
        </div>
        <button onClick={load} disabled={loading}
                className="bg-admin-600 hover:bg-admin-500 text-white text-xs font-bold px-4 py-2 rounded-lg disabled:opacity-60">
          {loading ? "Loading…" : "Apply"}
        </button>
        <div className="flex gap-2 ms-auto">
          <button onClick={() => download("csv")} disabled={!!exporting || !rows?.length}
                  className="flex items-center gap-1.5 bg-white hover:bg-gray-50 border border-gray-300 text-slate-700 text-xs font-bold px-3 py-2 rounded-lg disabled:opacity-60">
            <Download className="w-3.5 h-3.5" /> {exporting === "csv" ? "…" : "CSV"}
          </button>
          <button onClick={() => download("xlsx")} disabled={!!exporting || !rows?.length}
                  className="flex items-center gap-1.5 bg-white hover:bg-gray-50 border border-gray-300 text-slate-700 text-xs font-bold px-3 py-2 rounded-lg disabled:opacity-60">
            <FileSpreadsheet className="w-3.5 h-3.5 text-emerald-600" /> {exporting === "xlsx" ? "…" : "Excel"}
          </button>
          <button onClick={() => download("pdf")} disabled={!!exporting || !rows?.length}
                  className="flex items-center gap-1.5 bg-white hover:bg-gray-50 border border-gray-300 text-slate-700 text-xs font-bold px-3 py-2 rounded-lg disabled:opacity-60">
            <FileText className="w-3.5 h-3.5 text-rose-600" /> {exporting === "pdf" ? "…" : "PDF"}
          </button>
        </div>
      </div>

      {error && <p className="mt-3 text-xs text-rose-600">{error}</p>}

      {!rows ? (
        <div className="mt-4 h-32 rounded-xl bg-gray-50 animate-pulse" />
      ) : rows.length === 0 ? (
        <p className="mt-4 text-sm text-slate-600">No wallet matches those filters.</p>
      ) : (
        <div className="mt-4 overflow-x-auto max-h-[560px] overflow-y-auto">
          <table className="w-full text-start text-xs">
            <thead className="text-slate-500 border-b border-gray-200 sticky top-0 bg-white">
              <tr>
                <Th label="Customer" sortKey="name" />
                <Th label="Contact" />
                <Th label="Role" />
                <Th label="Cash" sortKey="default" />
                <Th label="Reward" sortKey="reward" />
                <Th label="Commission" sortKey="commission" />
                <Th label="Total" sortKey="total" />
                <Th label="Last activity" sortKey="last_activity" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {rows.map((r) => (
                <tr key={r.user_id}>
                  <td className="py-2.5">
                    <div className="font-semibold text-slate-900">{r.customer_name}</div>
                    <div className="text-[10px] text-slate-400">{r.status}</div>
                  </td>
                  <td className="py-2.5 text-slate-600">
                    <div>{r.email}</div>
                    {r.phone && <div className="text-[10px] text-slate-500">{r.phone}</div>}
                  </td>
                  <td className="py-2.5 text-slate-500">{r.role}</td>
                  <td className="py-2.5 font-mono text-emerald-700">€{r.default_balance}</td>
                  <td className="py-2.5 font-mono text-violet-700">€{r.reward_balance}</td>
                  <td className="py-2.5 font-mono text-sky-700">€{r.commission_balance}</td>
                  <td className="py-2.5 font-mono font-bold text-slate-900">€{r.total_balance}</td>
                  <td className="py-2.5 text-slate-500 whitespace-nowrap">{r.last_activity || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
