"use client";

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { LifeBuoy } from "lucide-react";
import { api } from "@/lib/api";
import { useAppSettings } from "@/lib/AppSettingsContext";
import EsimStatusView, { EsimStatus } from "@/components/esim/EsimStatusView";

// The public tracking link from the delivery email. No login: the person
// holding the eSIM may not have an account at all, because a travel agency can
// buy it on their behalf. Keyed on a 128-bit random token, so unlike a
// sequential id it can't be walked to find other customers' eSIMs.
export default function TrackEsimPage() {
  const { publicSettings } = useAppSettings();
  const params = useParams();
  const token = String(params?.token || "");
  const [data, setData] = useState<EsimStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [notFound, setNotFound] = useState(false);

  const load = useCallback(async () => {
    setData(await api.getPublicEsimStatus(token));
  }, [token]);

  useEffect(() => {
    load()
      .catch(() => setNotFound(true))
      .finally(() => setLoading(false));
  }, [load]);

  const refresh = async () => {
    setRefreshing(true);
    try {
      await load();
    } catch {
      // Keep whatever is on screen; the view reports supplier trouble itself.
    } finally {
      setRefreshing(false);
    }
  };

  if (loading) {
    return (
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-12 space-y-4">
        <div className="h-8 w-56 rounded bg-gray-100 animate-pulse" />
        <div className="h-32 rounded-2xl bg-gray-100 animate-pulse" />
        <div className="h-64 rounded-2xl bg-gray-100 animate-pulse" />
      </div>
    );
  }

  if (notFound || !data) {
    const support = publicSettings?.support_email;
    return (
      <div className="max-w-xl mx-auto px-4 py-20 text-center">
        <div className="w-12 h-12 rounded-xl bg-gray-100 text-slate-400 flex items-center justify-center mx-auto mb-4">
          <LifeBuoy className="w-6 h-6" />
        </div>
        <h1 className="text-xl font-bold text-slate-900">This tracking link isn&apos;t valid</h1>
        <p className="text-xs text-slate-500 mt-2">
          Check you copied the whole link from your eSIM email. If it still doesn&apos;t work
          {support ? <>, email <a href={`mailto:${support}`} className="font-semibold text-brand-600 underline">{support}</a></> : null}.
        </p>
        <Link href="/" className="mt-6 inline-block text-xs font-bold text-brand-600 underline">Go to the homepage</Link>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
      {/* The site header and footer come from the root layout, so this page
          only needs to say what it is. */}
      <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 mb-4">Live eSIM status</p>

      <EsimStatusView data={data} refreshing={refreshing} onRefresh={refresh} />

      <div className="mt-8 pt-6 border-t border-gray-200 text-center">
        <p className="text-xs text-slate-500">
          Keep this link to check your data any time.{" "}
          <Link href="/" className="font-semibold text-brand-600 underline">Need another eSIM?</Link>
        </p>
        {publicSettings?.support_email && (
          <p className="text-[11px] text-slate-400 mt-1">
            Trouble installing? Email{" "}
            <a href={`mailto:${publicSettings.support_email}`} className="underline">{publicSettings.support_email}</a>
          </p>
        )}
      </div>
    </div>
  );
}
