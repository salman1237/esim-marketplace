"use client";

import React, { useEffect, useState } from "react";
import { CheckCircle2, CreditCard, Eye, EyeOff, PlugZap, RotateCcw, XCircle } from "lucide-react";
import { api } from "@/lib/api";
import ConfirmDialog from "@/components/ConfirmDialog";
import { CopyButton } from "@/components/merchant/shared";

function getToken() {
  try {
    return localStorage.getItem("esim_token");
  } catch {
    return null;
  }
}

const inputCls = "w-full bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900";
const HOSTS: Record<string, string> = { live: "engine.shurjopayment.com", sandbox: "sandbox.shurjopayment.com" };

export default function ShurjoPayCard() {
  const [config, setConfig] = useState<any | null>(null);
  const [mode, setMode] = useState("live");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [prefix, setPrefix] = useState("");
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [resetOpen, setResetOpen] = useState(false);
  const [test, setTest] = useState<{ ok: boolean; message: string } | null>(null);
  const [notice, setNotice] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [limits, setLimits] = useState<any | null>(null);
  const [minTopup, setMinTopup] = useState("");
  const [maxTopup, setMaxTopup] = useState("");
  const [savingLimits, setSavingLimits] = useState(false);
  const [limitsNotice, setLimitsNotice] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  const applyLimits = (l: any) => {
    setLimits(l);
    setMinTopup(String(Number(l.min)));
    setMaxTopup(String(Number(l.max)));
  };

  useEffect(() => {
    const token = getToken();
    if (!token) return;
    api.getTopupLimits(token).then(applyLimits).catch(() => {});
  }, []);

  const saveLimits = async () => {
    const token = getToken();
    if (!token) return;
    setSavingLimits(true);
    setLimitsNotice(null);
    try {
      applyLimits(await api.updateTopupLimits(token, { min: minTopup.trim(), max: maxTopup.trim() }));
      setLimitsNotice({ kind: "ok", text: "Saved — the wallet page and the API use these straight away." });
    } catch (err: any) {
      setLimitsNotice({ kind: "error", text: err.message || "Couldn't save the limits" });
    } finally {
      setSavingLimits(false);
    }
  };

  const apply = (c: any) => {
    setConfig(c);
    setMode(c.mode === "sandbox" ? "sandbox" : "live");
    setUsername(c.source === "admin" ? c.username : "");
    setPrefix(c.source === "admin" ? c.prefix : "");
    setPassword("");
  };

  useEffect(() => {
    const token = getToken();
    if (!token) return;
    api.getShurjoPayConfig(token).then(apply).catch((err: any) => setNotice({ kind: "error", text: err.message || "Couldn't load ShurjoPay settings" }));
  }, []);

  const savedByAdmin = config?.source === "admin";
  const form = () => ({ mode, username: username.trim(), prefix: prefix.trim(), ...(password ? { password } : {}) });
  const canSubmit = username.trim() && prefix.trim() && (password || savedByAdmin);

  const save = async () => {
    const token = getToken();
    if (!token || !canSubmit) return;
    setSaving(true);
    setNotice(null);
    try {
      apply(await api.updateShurjoPayConfig(token, form()));
      setNotice({ kind: "ok", text: `Saved — ShurjoPay ${mode === "live" ? "LIVE" : "sandbox"} is now used for every payment.` });
    } catch (err: any) {
      setNotice({ kind: "error", text: err.message || "Couldn't save" });
    } finally {
      setSaving(false);
    }
  };

  const runTest = async () => {
    const token = getToken();
    if (!token) return;
    setTesting(true);
    setTest(null);
    try {
      // Tests what's in the form; with an empty form, the settings in use.
      const res = await api.testShurjoPayConfig(token, canSubmit ? form() : undefined);
      setTest({ ok: res.ok, message: res.message });
    } catch (err: any) {
      setTest({ ok: false, message: err.message || "Test failed" });
    } finally {
      setTesting(false);
    }
  };

  const reset = async () => {
    const token = getToken();
    if (!token) return;
    setSaving(true);
    try {
      apply(await api.resetShurjoPayConfig(token));
      setNotice({ kind: "ok", text: "Removed — the server's own ShurjoPay settings are used again." });
    } catch (err: any) {
      setNotice({ kind: "error", text: err.message || "Couldn't reset" });
    } finally {
      setSaving(false);
      setResetOpen(false);
    }
  };

  return (
    <div className="glass-panel rounded-2xl p-6 border border-gray-200">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-base font-bold text-slate-900 flex items-center gap-2">
            <CreditCard className="w-4 h-4 text-admin-600" /> ShurjoPay gateway
          </h3>
          <p className="text-xs text-slate-500 mt-1 max-w-2xl">
            Credentials for card and mobile-banking payments. Changes apply to the next payment — no redeploy. The password
            is stored encrypted and never shown again.
          </p>
        </div>
        {config && (
          <span className={`text-[11px] font-bold px-2.5 py-1 rounded-full border ${
            config.mode === "live" ? "bg-emerald-50 text-emerald-700 border-emerald-200" : "bg-amber-50 text-amber-700 border-amber-200"
          }`}>
            In use: {config.mode === "live" ? "LIVE" : config.mode === "sandbox" ? "SANDBOX (test payments)" : config.mode}
            {" · "}{savedByAdmin ? "set here" : "server settings"}
          </span>
        )}
      </div>

      {config?.saved_password_unreadable && (
        <p className="mt-3 text-xs text-rose-700 bg-rose-50 border border-rose-200 rounded-lg px-3 py-2">
          The saved password can no longer be read (the server&apos;s secret key changed). Re-enter it and save.
        </p>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-4">
        <div className="md:col-span-2">
          <label className="text-[11px] text-slate-700 font-semibold block mb-1">Environment</label>
          <div className="flex gap-2">
            {(["live", "sandbox"] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setMode(m)}
                className={`flex-1 text-start rounded-lg border px-3 py-2 ${mode === m ? "border-admin-500 bg-admin-50" : "border-gray-300 bg-white hover:bg-gray-50"}`}
              >
                <div className="text-xs font-bold text-slate-900">{m === "live" ? "Live — real money" : "Sandbox — test only"}</div>
                <div className="text-[10px] font-mono text-slate-500">https://{HOSTS[m]}</div>
              </button>
            ))}
          </div>
        </div>
        <div>
          <label className="text-[11px] text-slate-700 font-semibold block mb-1">API username</label>
          <input className={inputCls} value={username} autoComplete="off" onChange={(e) => setUsername(e.target.value)} placeholder={config && !savedByAdmin ? `server: ${config.environment.username}` : ""} />
        </div>
        <div>
          <label className="text-[11px] text-slate-700 font-semibold block mb-1">Store unique code (prefix)</label>
          <input className={`${inputCls} font-mono uppercase`} value={prefix} maxLength={10} onChange={(e) => setPrefix(e.target.value.toUpperCase())} placeholder={config && !savedByAdmin ? `server: ${config.environment.prefix}` : "e.g. TRI"} />
        </div>
        <div className="md:col-span-2">
          <label className="text-[11px] text-slate-700 font-semibold block mb-1">API password</label>
          <div className="relative">
            <input
              className={`${inputCls} pe-9 font-mono`}
              type={showPassword ? "text" : "password"}
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={savedByAdmin ? "•••••••• saved — leave blank to keep" : "Required"}
            />
            <button type="button" onClick={() => setShowPassword(!showPassword)} className="absolute end-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-700" aria-label={showPassword ? "Hide password" : "Show password"}>
              {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </button>
          </div>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3 mt-4">
        <button type="button" onClick={save} disabled={!canSubmit || saving} className="bg-admin-600 hover:bg-admin-500 disabled:opacity-50 text-white text-xs font-bold px-4 py-2.5 rounded-xl">
          {saving ? "Saving…" : "Save ShurjoPay settings"}
        </button>
        <button type="button" onClick={runTest} disabled={testing} className="flex items-center gap-1.5 bg-white hover:bg-gray-50 border border-gray-300 text-slate-700 text-xs font-bold px-4 py-2.5 rounded-xl disabled:opacity-60">
          <PlugZap className="w-3.5 h-3.5" /> {testing ? "Testing…" : canSubmit ? "Test these credentials" : "Test current connection"}
        </button>
        {savedByAdmin && (
          <button type="button" onClick={() => setResetOpen(true)} className="flex items-center gap-1 text-xs text-slate-600 hover:text-rose-600">
            <RotateCcw className="w-3.5 h-3.5" /> Use server settings instead
          </button>
        )}
      </div>
      {test && (
        <p className={`mt-3 text-xs font-medium flex items-center gap-1.5 ${test.ok ? "text-emerald-700" : "text-rose-700"}`}>
          {test.ok ? <CheckCircle2 className="w-4 h-4" /> : <XCircle className="w-4 h-4" />} {test.message}
        </p>
      )}
      {notice && <p className={`text-xs font-medium mt-3 ${notice.kind === "ok" ? "text-emerald-600" : "text-rose-600"}`}>{notice.text}</p>}

      <div className="mt-5 rounded-xl border border-gray-200 p-3">
        <div className="text-[11px] font-semibold text-slate-600 mb-1">Wallet top-up limits ({limits?.currency || "EUR"})</div>
        <p className="text-[11px] text-slate-500 mb-2">
          Lower the minimum to run a small live test (1 EUR is about 140 BDT), then put it back.
        </p>
        <div className="flex flex-wrap items-end gap-2">
          <div>
            <label className="text-[11px] text-slate-700 font-semibold block mb-1">Minimum</label>
            <input className={`${inputCls} w-28 font-mono`} value={minTopup} onChange={(e) => setMinTopup(e.target.value)} inputMode="decimal" />
          </div>
          <div>
            <label className="text-[11px] text-slate-700 font-semibold block mb-1">Maximum</label>
            <input className={`${inputCls} w-28 font-mono`} value={maxTopup} onChange={(e) => setMaxTopup(e.target.value)} inputMode="decimal" />
          </div>
          <button
            type="button"
            onClick={saveLimits}
            disabled={savingLimits || !minTopup.trim() || !maxTopup.trim()}
            className="bg-slate-900 hover:bg-slate-800 disabled:opacity-50 text-white text-xs font-bold px-3 py-2 rounded-lg"
          >
            {savingLimits ? "Saving…" : "Save limits"}
          </button>
          {limits && (
            <span className="text-[11px] text-slate-500 pb-2">
              now {Number(limits.min).toFixed(2)} – {Number(limits.max).toFixed(2)}
            </span>
          )}
        </div>
        {limitsNotice && <p className={`text-[11px] mt-2 ${limitsNotice.kind === "ok" ? "text-emerald-600" : "text-rose-600"}`}>{limitsNotice.text}</p>}
      </div>

      {config && (
        <div className="mt-5 rounded-xl bg-gray-50 border border-gray-200 p-3 space-y-1.5">
          <div className="text-[11px] font-semibold text-slate-600">URLs to give ShurjoPay</div>
          {[
            ["Success / return URL", config.urls.return_url],
            ["Cancel / failed URL", config.urls.cancel_url],
            ["IPN URL", config.urls.ipn_url],
          ].map(([label, url]) => (
            <div key={label} className="flex flex-wrap items-center justify-between gap-2 text-xs">
              <span className="text-slate-500">{label}</span>
              <span className="flex items-center gap-2 font-mono text-slate-800 break-all">{url} <CopyButton value={url} /></span>
            </div>
          ))}
        </div>
      )}

      <ConfirmDialog
        open={resetOpen}
        title="Remove the saved ShurjoPay credentials?"
        tone="danger"
        icon={<RotateCcw className="w-5 h-5" />}
        confirmLabel="Remove"
        busy={saving}
        onConfirm={reset}
        onCancel={() => setResetOpen(false)}
      >
        <p>
          Payments will use the server&apos;s own ShurjoPay settings again
          {config ? <> — currently <strong>{config.environment.mode === "live" ? "LIVE" : "SANDBOX"}</strong> ({config.environment.username})</> : null}.
        </p>
      </ConfirmDialog>
    </div>
  );
}
