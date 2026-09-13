"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, BookOpen, KeyRound, Send, ShieldCheck, Webhook } from "lucide-react";
import { api } from "@/lib/api";
import { CopyButton, Panel, formatDateTime, getToken } from "./shared";

export default function ApiAccessTab() {
  const [access, setAccess] = useState<any | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [webhookUrl, setWebhookUrl] = useState("");
  const [savingWebhook, setSavingWebhook] = useState(false);
  const [webhookMessage, setWebhookMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [revealedSecret, setRevealedSecret] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<any | null>(null);

  const load = async () => {
    const token = getToken();
    if (!token) return;
    try {
      const data = await api.getMerchantApiAccess(token);
      setAccess(data);
      setWebhookUrl(data.webhook.url || "");
    } catch (err: any) {
      setError(err.message || "Couldn't load API access");
    }
  };

  useEffect(() => {
    load();
  }, []);

  const saveWebhook = async (clear: boolean) => {
    const token = getToken();
    if (!token) return;
    if (!clear && access?.webhook.configured) {
      const ok = window.confirm("Saving generates a NEW signing secret and the current one stops working immediately. Continue?");
      if (!ok) return;
    }
    if (clear && !window.confirm("Remove your webhook? You'll only be able to poll for order updates.")) return;

    setSavingWebhook(true);
    setWebhookMessage(null);
    setTestResult(null);
    try {
      const res = await api.setMerchantWebhook(token, clear ? null : webhookUrl.trim());
      setRevealedSecret(res.webhook_secret);
      setWebhookMessage({ kind: "ok", text: clear ? "Webhook removed." : "Webhook saved." });
      await load();
    } catch (err: any) {
      setWebhookMessage({ kind: "error", text: err.message || "Couldn't save the webhook" });
    } finally {
      setSavingWebhook(false);
    }
  };

  const sendTest = async () => {
    const token = getToken();
    if (!token) return;
    setTesting(true);
    setTestResult(null);
    try {
      setTestResult(await api.sendMerchantTestWebhook(token));
    } catch (err: any) {
      setTestResult({ delivered: false, status_code: null, error: err.message });
    } finally {
      setTesting(false);
    }
  };

  if (error) return <Panel><p className="text-xs text-rose-600">{error}</p></Panel>;
  if (!access) return <div className="h-40 rounded-2xl bg-gray-100 animate-pulse" />;

  const quickStart = `# 1. Exchange your API key for a 1-hour access token
curl -s -X POST ${access.base_url}/auth/token \\
  -H "Content-Type: application/json" \\
  -d '{"api_key": "esim_live_..."}'

# 2. Place an order (safe to retry with the same customer_reference)
curl -s -X POST ${access.base_url}/orders \\
  -H "Authorization: Bearer <access_token>" \\
  -H "Content-Type: application/json" \\
  -d '{"product_id": "<product id>", "customer_reference": "<your order id>"}'`;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Panel title="API key" actions={<KeyRound className="w-4 h-4 text-merchant-600" />}>
          {access.key.active ? (
            <dl className="space-y-2.5 text-xs">
              <div className="flex justify-between"><dt className="text-slate-500">Status</dt><dd className="font-bold text-emerald-600">Active</dd></div>
              <div className="flex justify-between"><dt className="text-slate-500">Key</dt><dd className="font-mono text-slate-900">{access.key.prefix}…</dd></div>
              <div className="flex justify-between"><dt className="text-slate-500">Issued</dt><dd className="text-slate-900">{formatDateTime(access.key.created_at)}</dd></div>
              <div className="flex justify-between"><dt className="text-slate-500">Last used</dt><dd className="text-slate-900">{formatDateTime(access.key.last_used_at)}</dd></div>
            </dl>
          ) : (
            <p className="text-xs text-slate-600">
              No API key has been issued to your account yet. Contact Triptel support to request Partner API access.
            </p>
          )}
          <p className="mt-4 text-[11px] text-slate-500 leading-relaxed">
            For security the full key is shown only once, when Triptel issues it. If it is lost or may have leaked, contact
            support to rotate or revoke it — revocation takes effect on the very next API call.
          </p>
        </Panel>

        <Panel title="How authentication works" actions={<ShieldCheck className="w-4 h-4 text-merchant-600" />}>
          <ol className="list-decimal ps-4 space-y-1.5 text-xs text-slate-600">
            <li>Keep your <strong>API key</strong> (<code>esim_live_…</code>) on your server only — never in a browser or app.</li>
            <li>Exchange it at <code>POST /auth/token</code> for a <strong>1-hour access token</strong>.</li>
            <li>Send <code>Authorization: Bearer &lt;token&gt;</code> on every other call; get a new token when it expires.</li>
            <li>Verify every webhook with the <code>X-Webhook-Signature</code> header (HMAC-SHA256 of the raw body, keyed with your webhook secret).</li>
          </ol>
          <div className="mt-4 flex flex-wrap items-center gap-2 text-xs">
            <span className="text-slate-500">Base URL</span>
            <code className="font-mono bg-gray-100 text-slate-900 px-2 py-1 rounded">{access.base_url}</code>
            <CopyButton value={access.base_url} />
          </div>
          <Link href="/api-docs" className="mt-3 inline-flex items-center gap-1.5 text-xs font-bold text-brand-600 hover:text-brand-700">
            <BookOpen className="w-3.5 h-3.5" /> Read the full API documentation
          </Link>
        </Panel>
      </div>

      <Panel
        title="Webhook"
        description="We POST the order to this URL the moment it completes or fails."
        actions={<Webhook className="w-4 h-4 text-merchant-600" />}
      >
        <div className="flex flex-col md:flex-row gap-2">
          <input
            type="url"
            value={webhookUrl}
            onChange={(e) => setWebhookUrl(e.target.value)}
            placeholder="https://api.yourcompany.com/webhooks/triptel"
            className="flex-1 bg-white border border-gray-300 rounded-xl px-3 py-2 text-xs text-slate-900 font-mono"
          />
          <button disabled={savingWebhook || !webhookUrl.trim()} onClick={() => saveWebhook(false)} className="px-4 py-2 rounded-xl bg-merchant-600 hover:bg-merchant-500 disabled:opacity-60 text-white text-xs font-bold">
            {access.webhook.configured ? "Save & rotate secret" : "Save webhook"}
          </button>
          {access.webhook.configured && (
            <>
              <button disabled={testing} onClick={sendTest} className="px-4 py-2 rounded-xl border border-gray-200 bg-white hover:bg-gray-50 disabled:opacity-60 text-xs font-bold text-slate-700 flex items-center justify-center gap-1.5">
                <Send className="w-3.5 h-3.5" /> {testing ? "Sending…" : "Send test"}
              </button>
              <button disabled={savingWebhook} onClick={() => saveWebhook(true)} className="px-4 py-2 rounded-xl border border-rose-200 bg-white hover:bg-rose-50 text-xs font-bold text-rose-600">
                Remove
              </button>
            </>
          )}
        </div>
        <p className="text-[11px] text-slate-500 mt-2">Must be a public https:// URL. Respond with any 2xx status within 10 seconds.</p>

        {webhookMessage && (
          <p className={`mt-3 text-xs font-medium ${webhookMessage.kind === "ok" ? "text-emerald-600" : "text-rose-600"}`}>{webhookMessage.text}</p>
        )}

        {revealedSecret && (
          <div className="mt-4 p-4 rounded-xl bg-amber-50 border border-amber-200">
            <div className="flex items-center gap-2 text-xs font-bold text-amber-800">
              <AlertTriangle className="w-4 h-4" /> Your new webhook signing secret — shown only once
            </div>
            <div className="mt-2 flex items-center gap-2">
              <code className="flex-1 font-mono text-xs bg-white border border-amber-200 rounded-lg px-2 py-1.5 break-all">{revealedSecret}</code>
              <CopyButton value={revealedSecret} />
            </div>
            <p className="text-[11px] text-amber-800 mt-2">Store it in your server&apos;s secrets now. The previous secret has stopped working.</p>
          </div>
        )}

        {testResult && (
          <div className={`mt-4 p-3 rounded-xl border text-xs ${testResult.delivered ? "bg-emerald-50 border-emerald-200 text-emerald-700" : "bg-rose-50 border-rose-200 text-rose-700"}`}>
            {testResult.delivered
              ? `Test delivered — your endpoint answered HTTP ${testResult.status_code}.`
              : testResult.status_code
              ? `Your endpoint answered HTTP ${testResult.status_code}. It must return a 2xx status.`
              : testResult.error || "Couldn't reach your endpoint."}
            <div className="text-[11px] opacity-80 mt-1">
              Test deliveries carry <code>{`"event": "webhook.test"`}</code> and an <code>X-Webhook-Event: webhook.test</code> header, signed like real ones.
            </div>
          </div>
        )}

        <h4 className="text-xs font-bold text-slate-900 mt-6 mb-2">Recent deliveries</h4>
        <div className="overflow-x-auto">
          <table className="w-full text-start text-xs">
            <thead className="text-slate-500 border-b border-gray-200">
              <tr>
                <th className="py-2 pe-3">Date</th>
                <th className="py-2 pe-3">Order</th>
                <th className="py-2 pe-3">Attempt</th>
                <th className="py-2">Result</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {access.recent_deliveries.map((d: any, i: number) => (
                <tr key={i}>
                  <td className="py-2 pe-3 text-slate-500 whitespace-nowrap">{formatDateTime(d.created_at)}</td>
                  <td className="py-2 pe-3 font-mono text-brand-600">{d.order_no}</td>
                  <td className="py-2 pe-3 text-slate-700">{d.attempt}</td>
                  <td className={`py-2 font-bold ${d.success ? "text-emerald-600" : "text-rose-600"}`}>
                    {d.success ? "Delivered" : "Failed"}{d.response_status ? ` · HTTP ${d.response_status}` : ""}
                  </td>
                </tr>
              ))}
              {access.recent_deliveries.length === 0 && (
                <tr><td colSpan={4} className="py-6 text-center text-slate-500">No webhook deliveries yet.</td></tr>
              )}
            </tbody>
          </table>
        </div>
        <p className="text-[11px] text-slate-500 mt-2">Failed deliveries are retried every 5 minutes, up to 3 attempts in total.</p>
      </Panel>

      <Panel title="Quick start">
        <div className="relative">
          <pre className="p-4 rounded-xl bg-slate-900 text-slate-100 text-[11px] overflow-x-auto whitespace-pre">{quickStart}</pre>
          <div className="absolute top-2 end-2"><CopyButton value={quickStart} /></div>
        </div>
      </Panel>
    </div>
  );
}
