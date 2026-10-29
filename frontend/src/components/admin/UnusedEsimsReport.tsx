"use client";

import React, { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Download, FileSpreadsheet, FileText, RefreshCw, Search } from "lucide-react";
import { api } from "@/lib/api";
import { saveBlob } from "@/components/finance/StatementView";

type Row = {
  type: "REAL" | "TEST";
  order_no: string;
  purchased_at: string;
  customer_name: string;
  customer_email: string;
  customer_phone: string | null;
  product: string;
  country: string;
  vivape_trx_id: string;
  iccid: string | null;
  supplier_status: string | null;
  lookup_error: string | null;
  supplier_cost_eur: string;
  customer_refunded_eur: string;
};

type Summary = {
  count: number;
  real_count: number;
  test_count: number;
  supplier_cost_eur: string;
  real_cost_eur: string;
  test_cost_eur: string;
  iccids_resolved: number;
  generated_at: string;
};

function getToken() {
  try {
    return localStorage.getItem("esim_token");
  } catch {
    return null;
  }
}

export default function UnusedEsimsReport() {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [search, setSearch] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [typeFilter, setTypeFilter] = useState<"all" | "real" | "test">("all");
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [testIds, setTestIds] = useState("");
  const [savingTestIds, setSavingTestIds] = useState(false);

  const params = useCallback(() => {
    const p = new URLSearchParams();
    if (search.trim()) p.append("search", search.trim());
    if (dateFrom) p.append("date_from", `${dateFrom}T00:00:00`);
    if (dateTo) p.append("date_to", `${dateTo}T23:59:59`);
    if (typeFilter !== "all") p.append("report_type", typeFilter);
    return p;
  }, [search, dateFrom, dateTo, typeFilter]);

  const load = useCallback(async () => {
    const token = getToken();
    if (!token) return;
    setLoading(true);
    setNotice(null);
    try {
      const res = await api.getUnusedEsimsReport(token, params().toString());
      setRows(res.items);
      setSummary(res.summary);
    } catch (err: any) {
      setNotice(err.message || "Couldn't load the report");
    } finally {
      setLoading(false);
    }
  }, [params]);

  useEffect(() => {
    load();
    const token = getToken();
    if (token) {
      api.getTestEsimIdentifiers(token)
        .then((r) => setTestIds((r.identifiers || []).join("\n")))
        .catch(() => undefined);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const download = async (fmt: "csv" | "xlsx" | "pdf") => {
    const token = getToken();
    if (!token) return;
    setExporting(fmt);
    setNotice(null);
    try {
      const p = params();
      p.append("fmt", fmt);
      const blob = await api.downloadAuthed(token, `/api/v1/admin/reports/unused-esims/export?${p.toString()}`);
      saveBlob(blob, `unused-esims-${new Date().toISOString().slice(0, 10)}.${fmt}`);
    } catch (err: any) {
      setNotice(err.message || "Export failed");
    } finally {
      setExporting(null);
    }
  };

  const saveTestIds = async () => {
    const token = getToken();
    if (!token) return;
    setSavingTestIds(true);
    try {
      const identifiers = testIds.split(/[\n,;]+/).map((s) => s.trim()).filter(Boolean);
      const res = await api.updateTestEsimIdentifiers(token, identifiers);
      setTestIds((res.identifiers || []).join("\n"));
      setNotice("Saved. Reloading the report with the new real/test split…");
      await load();
    } catch (err: any) {
      setNotice(err.message || "Couldn't save the test list");
    } finally {
      setSavingTestIds(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="glass-panel rounded-2xl p-6 border border-gray-200">
        <h3 className="text-base font-bold text-slate-900 flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 text-amber-600" /> Unused eSIMs — paid to VivaPe, never delivered
        </h3>
        <p className="text-xs text-slate-500 mt-1 max-w-3xl">
          Orders VivaPe charged us for where the customer never received an eSIM. The ICCID is fetched live from
          VivaPe for each one — it is not stored here, because no eSIM profile was ever created. This is the list to
          reconcile with VivaPe.
        </p>

        {summary && (
          <div className="mt-4 grid grid-cols-2 sm:grid-cols-4 gap-3">
            <div className="rounded-xl border border-gray-200 bg-gray-50 px-4 py-3">
              <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Total</div>
              <div className="text-xl font-black text-slate-900">{summary.count}</div>
              <div className="text-[11px] text-slate-500">€{summary.supplier_cost_eur} cost</div>
            </div>
            <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3">
              <div className="text-[10px] font-bold uppercase tracking-wider text-emerald-700">Real customers</div>
              <div className="text-xl font-black text-emerald-800">{summary.real_count}</div>
              <div className="text-[11px] text-emerald-700">€{summary.real_cost_eur}</div>
            </div>
            <div className="rounded-xl border border-sky-200 bg-sky-50 px-4 py-3">
              <div className="text-[10px] font-bold uppercase tracking-wider text-sky-700">Testing</div>
              <div className="text-xl font-black text-sky-800">{summary.test_count}</div>
              <div className="text-[11px] text-sky-700">€{summary.test_cost_eur}</div>
            </div>
            <div className="rounded-xl border border-gray-200 bg-gray-50 px-4 py-3">
              <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500">ICCIDs found</div>
              <div className="text-xl font-black text-slate-900">{summary.iccids_resolved}/{summary.count}</div>
              <div className="text-[11px] text-slate-500">{summary.generated_at}</div>
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
                placeholder="Name, email, phone, ICCID, order no…"
                className="w-full bg-white border border-gray-300 rounded-lg ps-9 pe-3 py-2 text-xs text-slate-900"
              />
            </div>
          </div>
          <div>
            <label className="text-[11px] font-bold text-slate-600 block mb-1">From</label>
            <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)}
                   className="bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900" />
          </div>
          <div>
            <label className="text-[11px] font-bold text-slate-600 block mb-1">To</label>
            <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)}
                   className="bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900" />
          </div>
          <div>
            <label className="text-[11px] font-bold text-slate-600 block mb-1">Type</label>
            <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value as any)}
                    className="bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900">
              <option value="all">Real + Test</option>
              <option value="real">Real only</option>
              <option value="test">Test only</option>
            </select>
          </div>
          <button onClick={load} disabled={loading}
                  className="bg-admin-600 hover:bg-admin-500 text-white text-xs font-bold px-4 py-2 rounded-lg flex items-center gap-1.5 disabled:opacity-60">
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
            {loading ? "Loading…" : "Apply"}
          </button>
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
          <button onClick={() => download("csv")} disabled={!!exporting || !rows?.length}
                  className="flex items-center gap-1.5 bg-white hover:bg-gray-50 border border-gray-300 text-slate-700 text-xs font-bold px-4 py-2 rounded-lg disabled:opacity-60">
            <Download className="w-3.5 h-3.5" /> {exporting === "csv" ? "Preparing…" : "CSV"}
          </button>
          <button onClick={() => download("xlsx")} disabled={!!exporting || !rows?.length}
                  className="flex items-center gap-1.5 bg-white hover:bg-gray-50 border border-gray-300 text-slate-700 text-xs font-bold px-4 py-2 rounded-lg disabled:opacity-60">
            <FileSpreadsheet className="w-3.5 h-3.5 text-emerald-600" /> {exporting === "xlsx" ? "Preparing…" : "Excel"}
          </button>
          <button onClick={() => download("pdf")} disabled={!!exporting || !rows?.length}
                  className="flex items-center gap-1.5 bg-white hover:bg-gray-50 border border-gray-300 text-slate-700 text-xs font-bold px-4 py-2 rounded-lg disabled:opacity-60">
            <FileText className="w-3.5 h-3.5 text-rose-600" /> {exporting === "pdf" ? "Preparing…" : "PDF"}
          </button>
        </div>

        {notice && <p className="mt-3 text-xs font-medium text-slate-700">{notice}</p>}
      </div>

      <div className="glass-panel rounded-2xl p-6 border border-gray-200">
        <h4 className="text-sm font-bold text-slate-900">Which of these were your own testing?</h4>
        <p className="text-xs text-slate-500 mt-1 max-w-2xl">
          VivaPe asked for real and test separated. Paste the emails or ICCIDs you used for testing — one per line —
          and every row below is labelled accordingly, in the exports too.
        </p>
        <textarea
          value={testIds}
          onChange={(e) => setTestIds(e.target.value)}
          rows={4}
          placeholder={"tester@yourcompany.com\n89862103954300006454"}
          className="mt-3 w-full max-w-xl bg-white border border-gray-300 rounded-xl px-3 py-2 text-xs font-mono text-slate-900"
        />
        <div>
          <button onClick={saveTestIds} disabled={savingTestIds}
                  className="mt-2 bg-admin-600 hover:bg-admin-500 disabled:opacity-50 text-white text-xs font-bold px-4 py-2 rounded-lg">
            {savingTestIds ? "Saving…" : "Save & relabel"}
          </button>
        </div>
      </div>

      <div className="glass-panel rounded-2xl p-6 border border-gray-200">
        {!rows ? (
          <div className="h-32 rounded-xl bg-gray-50 animate-pulse" />
        ) : rows.length === 0 ? (
          <p className="text-sm text-slate-600">
            Nothing to claim — no order was charged by VivaPe without reaching a customer.
          </p>
        ) : (
          <div className="overflow-x-auto max-h-[600px] overflow-y-auto">
            <table className="w-full text-start text-xs">
              <thead className="text-slate-500 border-b border-gray-200 sticky top-0 bg-white">
                <tr>
                  <th className="py-2">Type</th>
                  <th className="py-2">Order No</th>
                  <th className="py-2">Purchased</th>
                  <th className="py-2">Customer</th>
                  <th className="py-2">Phone</th>
                  <th className="py-2">Package</th>
                  <th className="py-2">VivaPe Trx</th>
                  <th className="py-2">ICCID</th>
                  <th className="py-2">Cost</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {rows.map((r) => (
                  <tr key={r.order_no}>
                    <td className="py-2.5">
                      <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                        r.type === "TEST" ? "bg-sky-50 text-sky-700" : "bg-emerald-50 text-emerald-700"
                      }`}>{r.type}</span>
                    </td>
                    <td className="py-2.5 font-mono text-admin-600">{r.order_no}</td>
                    <td className="py-2.5 text-slate-500 whitespace-nowrap">{r.purchased_at}</td>
                    <td className="py-2.5 text-slate-700">
                      <div className="font-semibold">{r.customer_name}</div>
                      <div className="text-[10px] text-slate-500">{r.customer_email}</div>
                    </td>
                    <td className="py-2.5 text-slate-500">{r.customer_phone || "—"}</td>
                    <td className="py-2.5 text-slate-700">{r.country} · {r.product}</td>
                    <td className="py-2.5 font-mono text-slate-600">{r.vivape_trx_id}</td>
                    <td className="py-2.5 font-mono text-[11px]">
                      {r.iccid ? (
                        <button onClick={() => navigator.clipboard?.writeText(r.iccid!)}
                                className="text-admin-600 hover:underline" title="Copy ICCID">
                          {r.iccid}
                        </button>
                      ) : (
                        <span className="text-rose-600" title={r.lookup_error || "VivaPe did not return an ICCID"}>
                          not returned
                        </span>
                      )}
                    </td>
                    <td className="py-2.5 font-bold text-slate-900 whitespace-nowrap">€{r.supplier_cost_eur}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
