"use client";

import React, { useEffect, useState } from "react";
import { Wallet, Webhook } from "lucide-react";
import { api } from "@/lib/api";

function getToken() {
  try {
    return localStorage.getItem("esim_token");
  } catch {
    return null;
  }
}

// Account-level eSIM Access state - balance and the registered webhook
// URL. Not per-eSIM (that's the lifecycle actions in EsimLiveStatus),
// this is the one-time account setup an admin checks occasionally.
export default function EsimAccessAccountCard() {
  const [balance, setBalance] = useState<string | null>(null);
  const [balanceError, setBalanceError] = useState<string | null>(null);
  const [webhookUrl, setWebhookUrl] = useState<string | null>(null);
  const [webhookError, setWebhookError] = useState<string | null>(null);
  const [registering, setRegistering] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const loadBalance = async () => {
    const token = getToken();
    if (!token) return;
    try {
      const res = await api.getEsimAccessBalance(token);
      setBalance(res.balance);
      setBalanceError(null);
    } catch (err: any) {
      setBalanceError(err.message || "Couldn't load balance");
    }
  };

  const loadWebhook = async () => {
    const token = getToken();
    if (!token) return;
    try {
      const res = await api.getEsimAccessWebhook(token);
      setWebhookUrl(res.webhook_url || null);
      setWebhookError(null);
    } catch (err: any) {
      setWebhookError(err.message || "Couldn't load webhook status");
    }
  };

  useEffect(() => {
    loadBalance();
    loadWebhook();
  }, []);

  const registerWebhook = async () => {
    const token = getToken();
    if (!token) return;
    setRegistering(true);
    setNotice(null);
    try {
      const res = await api.setEsimAccessWebhook(token);
      setWebhookUrl(res.webhook_url);
      setNotice("Webhook registered - eSIM Access will now push status/usage updates here instead of relying only on polling.");
    } catch (err: any) {
      setNotice(err.message || "Couldn't register the webhook");
    } finally {
      setRegistering(false);
    }
  };

  const expectedUrl = typeof window !== "undefined" ? `${window.location.origin}/api/v1/webhooks/esimaccess` : null;
  const webhookMatches = webhookUrl && expectedUrl && webhookUrl === expectedUrl;

  return (
    <div className="glass-panel rounded-2xl p-6 border border-gray-200">
      <h3 className="text-base font-bold text-slate-900 flex items-center gap-2">
        <Wallet className="w-4 h-4 text-admin-600" /> eSIM Access Account
      </h3>
      <p className="text-xs text-slate-500 mt-1 max-w-2xl">
        Account balance and the inbound webhook that lets eSIM Access push order/eSIM/usage events here instead of
        this project only ever polling for them.
      </p>

      <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="rounded-xl border border-gray-200 bg-gray-50 px-4 py-3">
          <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Balance</div>
          {balanceError ? (
            <p className="text-xs text-rose-600 mt-1">{balanceError}</p>
          ) : balance === null ? (
            <div className="h-6 w-20 mt-1 rounded bg-gray-200 animate-pulse" />
          ) : (
            <div className="text-lg font-black text-slate-900 mt-0.5">${Number(balance).toFixed(2)}</div>
          )}
        </div>

        <div className="rounded-xl border border-gray-200 bg-gray-50 px-4 py-3">
          <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500 flex items-center gap-1">
            <Webhook className="w-3 h-3" /> Webhook
          </div>
          {webhookError ? (
            <p className="text-xs text-rose-600 mt-1">{webhookError}</p>
          ) : webhookUrl === null ? (
            <div className="h-6 w-32 mt-1 rounded bg-gray-200 animate-pulse" />
          ) : (
            <p className={`text-xs font-mono break-all mt-1 ${webhookMatches ? "text-emerald-700" : "text-amber-700"}`}>
              {webhookUrl || "Not registered"}
            </p>
          )}
          <button
            onClick={registerWebhook}
            disabled={registering}
            className="mt-2 bg-admin-600 hover:bg-admin-500 disabled:opacity-60 text-white text-[11px] font-bold px-3 py-1.5 rounded-lg"
          >
            {registering ? "Registering…" : "Register this server's webhook"}
          </button>
        </div>
      </div>

      {notice && <p className="text-xs font-medium mt-3 text-slate-700">{notice}</p>}
    </div>
  );
}
