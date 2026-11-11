"use client";

import React, { useEffect, useState } from "react";
import { Database, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import { useAppSettings } from "@/lib/AppSettingsContext";

type TopupOption = {
  package_code: string;
  title: string;
  data_amount_gb: string | number;
  validity_days: number;
  retail_price: string | number;
  currency: string;
};

type Flow =
  | { stage: "idle" }
  | { stage: "buying"; option: TopupOption }
  | { stage: "success"; option: TopupOption }
  | { stage: "error"; option: TopupOption; message: string };

// Only ever has options for an eSIM Access eSIM - an empty list from the
// backend is the ordinary case for every other supplier, so this panel
// renders nothing rather than an empty state in that (common) case.
export default function TopupPanel({ esimId }: { esimId: string }) {
  const { formatPrice } = useAppSettings();
  const [options, setOptions] = useState<TopupOption[] | null>(null);
  const [flow, setFlow] = useState<Flow>({ stage: "idle" });

  useEffect(() => {
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    api.getTopupOptions(token, esimId).then(setOptions).catch(() => setOptions([]));
  }, [esimId]);

  const buy = async (option: TopupOption) => {
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    setFlow({ stage: "buying", option });
    try {
      await api.purchaseTopup(token, esimId, option.package_code);
      setFlow({ stage: "success", option });
    } catch (err: any) {
      setFlow({ stage: "error", option, message: err.message || "Top-up failed. If you were charged, you've been refunded." });
    }
  };

  if (!options || options.length === 0) return null;

  return (
    <div className="mt-6 glass-panel rounded-2xl p-6 border border-gray-200">
      <h2 className="text-base font-bold text-slate-900 mb-1 flex items-center gap-2">
        <Database className="w-4 h-4 text-brand-600" /> Top Up This eSIM
      </h2>
      <p className="text-xs text-slate-500 mb-4">
        Running low on data? Add more without buying a new eSIM - these options are live from the network right now.
      </p>

      {flow.stage === "success" ? (
        <div className="rounded-xl bg-emerald-50 border border-emerald-200 p-4 text-sm text-emerald-800">
          Top-up complete — {flow.option.title} has been added to this eSIM.
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {options.map((o) => {
            const busy = flow.stage === "buying" && flow.option.package_code === o.package_code;
            return (
              <div key={o.package_code} className="rounded-xl border border-gray-200 p-4 flex items-center justify-between gap-3">
                <div>
                  <div className="text-sm font-bold text-slate-900">{Number(o.data_amount_gb)} GB</div>
                  <div className="text-xs text-slate-500">{o.validity_days} days validity</div>
                </div>
                <div className="text-end">
                  <div className="text-sm font-black text-emerald-600 mb-1">{formatPrice(Number(o.retail_price))}</div>
                  <button
                    onClick={() => buy(o)}
                    disabled={flow.stage === "buying"}
                    className="bg-brand-600 hover:bg-brand-500 disabled:opacity-60 text-white text-xs font-bold px-3 py-1.5 rounded-lg inline-flex items-center gap-1.5"
                  >
                    {busy && <Loader2 className="w-3 h-3 animate-spin" />}
                    {busy ? "Buying…" : "Buy"}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {flow.stage === "error" && (
        <p className="mt-3 text-xs text-rose-600">{flow.message}</p>
      )}
    </div>
  );
}
