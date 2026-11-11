"use client";

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, Check, Copy, Printer, Share2 } from "lucide-react";
import { api } from "@/lib/api";
import EsimStatusView, { EsimStatus } from "@/components/esim/EsimStatusView";
import TopupPanel from "@/components/esim/TopupPanel";

// The owner's view. Identical body to the public tracking link (one shared
// component), plus the link itself to copy or send on.
export default function EsimStatusPage() {
  const params = useParams();
  const id = String(params?.id || "");
  const [data, setData] = useState<EsimStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const load = useCallback(async () => {
    const token = localStorage.getItem("esim_token");
    if (!token) {
      window.location.href = `/auth/login?next=/my-esims/${id}`;
      return;
    }
    setData(await api.getEsimStatus(token, id));
  }, [id]);

  useEffect(() => {
    load()
      .catch((err) => setError(err.message || "Couldn't load this eSIM"))
      .finally(() => setLoading(false));
  }, [load]);

  const refresh = async () => {
    const token = localStorage.getItem("esim_token");
    if (!token) return;
    setRefreshing(true);
    try {
      setData(await api.refreshEsimStatus(token, id));
    } catch (err: any) {
      setError(err.message || "Couldn't refresh");
    } finally {
      setRefreshing(false);
    }
  };

  const share = async () => {
    if (!data?.share_url) return;
    if (navigator.share) {
      try {
        await navigator.share({ title: "My eSIM status", url: data.share_url });
        return;
      } catch {
        // Cancelled or not permitted here - fall through to copying.
      }
    }
    navigator.clipboard?.writeText(data.share_url).catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
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

  if (!data) {
    return (
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-16 text-center">
        <p className="text-sm text-slate-600">{error || "That eSIM could not be found."}</p>
        <Link href="/my-esims" className="mt-4 inline-block text-xs font-bold text-brand-600 underline">Back to My eSIMs</Link>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
      <Link href="/my-esims" className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-500 hover:text-slate-900 mb-4">
        <ArrowLeft className="w-3.5 h-3.5" /> Back to My eSIMs
      </Link>

      {error && <p className="mb-4 text-xs text-rose-600">{error}</p>}

      <EsimStatusView
        data={data}
        refreshing={refreshing}
        onRefresh={refresh}
        actions={
          <Link
            href={`/my-esims/${id}/print`}
            className="inline-flex items-center gap-1.5 bg-white hover:bg-gray-50 border border-gray-300 text-slate-700 text-xs font-bold px-3 py-2 rounded-xl"
          >
            <Printer className="w-3.5 h-3.5" /> Print
          </Link>
        }
      />

      <TopupPanel esimId={id} />

      {/* The tracking link, also sent in the delivery email. Anyone with it can
          see this page and install the eSIM - which is the point, and no more
          than the email already carries. */}
      {data.share_url && (
        <div className="mt-6 glass-panel rounded-2xl p-6 border border-gray-200">
          <h2 className="text-base font-bold text-slate-900 mb-1 flex items-center gap-2">
            <Share2 className="w-4 h-4 text-brand-600" /> Tracking link
          </h2>
          <p className="text-xs text-slate-500 mb-4">
            This page without needing to sign in — it&apos;s in your eSIM email too. Anyone you send it to can see the usage
            and install the eSIM, so only share it with whoever is using it.
          </p>
          <div className="flex flex-wrap gap-2">
            <input
              readOnly
              value={data.share_url}
              onFocus={(e) => e.currentTarget.select()}
              className="flex-1 min-w-[220px] bg-white border border-gray-300 rounded-xl px-3 py-2 text-xs font-mono text-slate-900"
            />
            <button
              onClick={share}
              className="inline-flex items-center gap-1.5 bg-brand-600 hover:bg-brand-500 text-white text-xs font-bold px-4 py-2 rounded-xl"
            >
              {copied ? <><Check className="w-3.5 h-3.5" /> Copied</> : <><Copy className="w-3.5 h-3.5" /> Copy link</>}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
