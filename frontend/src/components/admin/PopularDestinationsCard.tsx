"use client";

import React, { useEffect, useState } from "react";
import { Globe2, GripVertical } from "lucide-react";
import { api } from "@/lib/api";

type Props = {
  isSuperAdmin: boolean;
};

type Row = { id: number; iso2: string; name_en: string; flag_url: string | null; is_popular: boolean; popular_order: number };

function getToken() {
  try {
    return localStorage.getItem("esim_token");
  } catch {
    return null;
  }
}

export default function PopularDestinationsCard({ isSuperAdmin }: Props) {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [search, setSearch] = useState("");
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  const load = async (q?: string) => {
    const token = getToken();
    if (!token) return;
    try {
      const res = await api.getAdminCountries(token, q);
      setRows(res.countries);
    } catch (err: any) {
      setNotice({ kind: "error", text: err.message || "Couldn't load destinations" });
    }
  };

  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    const handle = setTimeout(() => load(search.trim() || undefined), 300);
    return () => clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  const toggle = (id: number) => {
    setRows((prev) => prev && prev.map((r) => (r.id === id ? { ...r, is_popular: !r.is_popular } : r)));
  };

  const move = (id: number, dir: -1 | 1) => {
    setRows((prev) => {
      if (!prev) return prev;
      const selected = prev.filter((r) => r.is_popular).sort((a, b) => a.popular_order - b.popular_order);
      const idx = selected.findIndex((r) => r.id === id);
      const swapWith = idx + dir;
      if (idx < 0 || swapWith < 0 || swapWith >= selected.length) return prev;
      [selected[idx], selected[swapWith]] = [selected[swapWith], selected[idx]];
      const order = new Map(selected.map((r, i) => [r.id, i]));
      return prev.map((r) => (order.has(r.id) ? { ...r, popular_order: order.get(r.id)! } : r));
    });
  };

  const save = async () => {
    const token = getToken();
    if (!token || !rows) return;
    setSaving(true);
    setNotice(null);
    try {
      const selected = rows.filter((r) => r.is_popular).sort((a, b) => a.popular_order - b.popular_order);
      const payload = rows.map((r) => ({
        id: r.id,
        is_popular: r.is_popular,
        popular_order: r.is_popular ? selected.findIndex((s) => s.id === r.id) : 0,
      }));
      const res = await api.updatePopularDestinations(token, payload);
      setRows(res.countries);
      setNotice({ kind: "ok", text: "Saved. The home page shows the new list right away." });
    } catch (err: any) {
      setNotice({ kind: "error", text: err.message || "Couldn't save the destination list" });
    } finally {
      setSaving(false);
    }
  };

  const selectedOrdered = (rows || []).filter((r) => r.is_popular).sort((a, b) => a.popular_order - b.popular_order);

  return (
    <div className="glass-panel rounded-2xl p-6 border border-gray-200">
      <h3 className="text-base font-bold text-slate-900 flex items-center gap-2">
        <Globe2 className="w-4 h-4 text-admin-600" /> Home page: Popular Destinations
      </h3>
      <p className="text-xs text-slate-500 mt-1 max-w-2xl">
        Pick which destinations show in the home page's Popular Destinations row, and the order they appear in.
        {!isSuperAdmin && " Only a Super Admin can change this."}
      </p>

      {selectedOrdered.length > 0 && (
        <div className="mt-4">
          <div className="text-xs font-bold text-slate-700 mb-1.5">Shown on the home page, in order</div>
          <div className="flex flex-col gap-1.5 max-w-md">
            {selectedOrdered.map((r, i) => (
              <div key={r.id} className="flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2">
                <GripVertical className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                <span className="text-xs font-bold text-emerald-900 flex-1">{r.name_en}</span>
                {isSuperAdmin && (
                  <div className="flex gap-1">
                    <button type="button" disabled={i === 0} onClick={() => move(r.id, -1)} className="px-1.5 py-0.5 text-[11px] rounded bg-white border border-emerald-200 disabled:opacity-30">↑</button>
                    <button type="button" disabled={i === selectedOrdered.length - 1} onClick={() => move(r.id, 1)} className="px-1.5 py-0.5 text-[11px] rounded bg-white border border-emerald-200 disabled:opacity-30">↓</button>
                    <button type="button" onClick={() => toggle(r.id)} className="px-1.5 py-0.5 text-[11px] rounded bg-white border border-rose-200 text-rose-600">Remove</button>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="mt-4">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search destinations to add…"
          className="w-full max-w-md bg-white border border-gray-300 rounded-xl px-3 py-2 text-xs text-slate-900"
        />
      </div>

      {!rows ? (
        <div className="mt-3 h-20 rounded-xl bg-gray-50 animate-pulse" />
      ) : (
        <div className="mt-3 max-w-md max-h-56 overflow-y-auto flex flex-col gap-1 pr-1">
          {rows.filter((r) => !r.is_popular).map((r) => (
            <label key={r.id} className="flex items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-gray-50 cursor-pointer">
              <input type="checkbox" checked={false} disabled={!isSuperAdmin} onChange={() => toggle(r.id)} className="w-3.5 h-3.5 accent-admin-600" />
              <span className="text-xs text-slate-700">{r.name_en}</span>
              <span className="text-[10px] text-slate-400 ms-auto">{r.iso2}</span>
            </label>
          ))}
          {rows.filter((r) => !r.is_popular).length === 0 && (
            <p className="text-[11px] text-slate-400 px-2 py-1.5">No more destinations match.</p>
          )}
        </div>
      )}

      {isSuperAdmin && (
        <button
          onClick={save}
          disabled={saving}
          className="mt-4 bg-admin-600 hover:bg-admin-500 disabled:opacity-50 text-white text-xs font-bold px-4 py-2.5 rounded-lg"
        >
          {saving ? "Saving…" : "Save"}
        </button>
      )}
      {notice && (
        <p className={`text-xs font-medium mt-3 ${notice.kind === "ok" ? "text-emerald-600" : "text-rose-600"}`}>{notice.text}</p>
      )}
    </div>
  );
}
