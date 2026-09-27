"use client";

import React, { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Mail, Save } from "lucide-react";
import { api } from "@/lib/api";

function getToken() {
  try {
    return localStorage.getItem("esim_token");
  } catch {
    return null;
  }
}

const inputCls = "w-full bg-white border border-gray-300 rounded-lg px-3 py-2 text-xs text-slate-900";

// Everything monetary is copied here: sign-ups, applications, approvals,
// referral and agent code use, sales, and withdrawals.
const COPIED = [
  "New accounts",
  "Partner & agent applications",
  "Partner & agent approvals",
  "Referral and agent codes being used",
  "Every sale",
  "Withdrawal requests, payouts and rejections",
];

export default function NotificationSettingsCard({ isSuperAdmin }: { isSuperAdmin: boolean }) {
  const [data, setData] = useState<any | null>(null);
  const [email, setEmail] = useState("");
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  const load = useCallback(async () => {
    const token = getToken();
    if (!token) return;
    const cfg = await api.getNotificationSettings(token);
    setData(cfg);
    setEmail(cfg.system_notice_email);
  }, []);

  useEffect(() => {
    load().catch((err) => setNotice({ kind: "error", text: err.message || "Couldn't load notification settings" }));
  }, [load]);

  const save = async () => {
    const token = getToken();
    if (!token) return;
    setSaving(true);
    setNotice(null);
    try {
      await api.updateNotificationSettings(token, email.trim());
      await load();
      setNotice({ kind: "ok", text: "Saved — new notices go to this address." });
    } catch (err: any) {
      setNotice({ kind: "error", text: err.message || "Couldn't save" });
    } finally {
      setSaving(false);
    }
  };

  if (!data) return <div className="glass-panel rounded-2xl border border-gray-200 h-40 animate-pulse" />;

  return (
    <div className="glass-panel rounded-2xl p-6 border border-gray-200">
      <h3 className="text-base font-bold text-slate-900 flex items-center gap-2">
        <Mail className="w-4 h-4 text-admin-600" /> Notification mailbox
      </h3>
      <p className="text-xs text-slate-500 mt-1 max-w-2xl">
        Every notice below is copied here, so the platform has one inbox for all activity without anyone remembering to
        CC it. Customers, partners and agents still get their own emails.
        {!isSuperAdmin && " Only a Super Admin can change this."}
      </p>

      <div className="flex flex-wrap items-end gap-2 mt-4">
        <div className="flex-1 min-w-[220px]">
          <label className="text-[11px] text-slate-700 font-semibold block mb-1">System address</label>
          <input
            className={inputCls}
            type="email"
            value={email}
            disabled={!isSuperAdmin}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        {isSuperAdmin && (
          <button
            type="button"
            onClick={save}
            disabled={saving || !email.trim() || email.trim() === data.system_notice_email}
            className="flex items-center gap-1.5 bg-admin-600 hover:bg-admin-500 disabled:opacity-50 text-white text-xs font-bold px-4 py-2.5 rounded-xl"
          >
            <Save className="w-3.5 h-3.5" /> {saving ? "Saving…" : "Save"}
          </button>
        )}
      </div>

      {!data.smtp_configured && (
        <p className="mt-3 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 flex items-start gap-2">
          <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
          Outgoing mail isn&apos;t configured on the server, so nothing is being sent yet.
        </p>
      )}

      <div className="mt-4 rounded-xl bg-gray-50 border border-gray-200 p-3">
        <div className="text-[11px] font-semibold text-slate-600 mb-1.5">Copied to this address</div>
        <ul className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-1">
          {COPIED.map((item) => (
            <li key={item} className="text-[11px] text-slate-500 flex items-start gap-1.5">
              <span className="mt-1.5 w-1 h-1 rounded-full bg-slate-400 shrink-0" /> {item}
            </li>
          ))}
        </ul>
        <p className="text-[11px] text-slate-400 mt-2">Sent from {data.sender}.</p>
      </div>

      {notice && <p className={`text-xs font-medium mt-3 ${notice.kind === "ok" ? "text-emerald-600" : "text-rose-600"}`}>{notice.text}</p>}
    </div>
  );
}
