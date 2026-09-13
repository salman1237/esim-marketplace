"use client";

import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import StatementView, { currentMonth } from "@/components/finance/StatementView";

export default function StatementTab() {
  const [month, setMonth] = useState(currentMonth());
  const [statement, setStatement] = useState<any | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const token = localStorage.getItem("esim_token");
    if (!token || !month) return;
    setLoading(true);
    setError(null);
    api
      .getMyStatement(token, month)
      .then(setStatement)
      .catch((err: any) => setError(err.message || "Couldn't load the statement"))
      .finally(() => setLoading(false));
  }, [month]);

  return (
    <div className="glass-panel rounded-2xl p-6 border border-gray-200 space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h3 className="text-base font-bold text-slate-900">Monthly statement</h3>
          <p className="text-xs text-slate-500 mt-1 max-w-xl">
            Every top-up, purchase, refund and commission for the month, with opening and closing balances. It&apos;s the
            same statement our finance team sees, so both sides work from one set of numbers.
          </p>
        </div>
        <div>
          <label className="text-[11px] text-slate-600 font-semibold block mb-1">Month</label>
          <input
            type="month"
            value={month}
            max={currentMonth()}
            onChange={(e) => setMonth(e.target.value)}
            className="bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900"
          />
        </div>
      </div>

      {error && <p className="text-xs text-rose-600">{error}</p>}
      {loading && !statement && <div className="h-40 rounded-xl bg-gray-50 animate-pulse" />}
      {statement && (
        <div className={loading ? "opacity-60" : ""}>
          <StatementView statement={statement} csvPath={`/api/v1/merchant/statement.csv?month=${month}`} csvName={`statement-${month}.csv`} />
        </div>
      )}
    </div>
  );
}
