"use client";

import React, { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api, API_BASE } from "@/lib/api";
import { formatDateTimeZoned } from "@/lib/datetime";

// Same approach as the eSIM print sheet: self-contained, light, and free of
// app chrome so it survives being printed or saved as a PDF for accounting.
export default function WithdrawalReceiptPage() {
  const params = useParams();
  const id = String(params?.id || "");
  const [item, setItem] = useState<any | null>(null);
  const [settings, setSettings] = useState<any>({});
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    const token = localStorage.getItem("esim_token");
    if (!token) {
      window.location.href = "/auth/login";
      return;
    }
    Promise.all([
      api.getWithdrawal(token, id),
      api.getPublicSettings().catch(() => ({})),
    ])
      .then(([withdrawal, s]) => {
        setItem(withdrawal);
        setSettings(s || {});
      })
      .catch(() => setNotFound(true))
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) {
    return <div style={{ padding: 48, fontFamily: "system-ui", color: "#475569" }}>Preparing your receipt…</div>;
  }
  if (notFound || !item) {
    return (
      <div style={{ padding: 48, fontFamily: "system-ui", color: "#475569" }}>
        <p>That withdrawal could not be found.</p>
        <a href="/wallet/withdraw" style={{ color: "#4f46e5" }}>Back to withdrawals</a>
      </div>
    );
  }

  const logo = settings.logo_light
    ? (settings.logo_light.startsWith("http") ? settings.logo_light : `${API_BASE}${settings.logo_light}`)
    : null;
  const brand = settings.platform_name || "Triptel";
  const paid = item.status === "PAID";
  const eur = (v: any) => `€${Number(v || 0).toFixed(2)}`;
  const payout = item.payout_amount
    ? `${Number(item.payout_amount).toLocaleString(undefined, { maximumFractionDigits: 2 })} ${item.payout_currency}`
    : "—";

  const rows: [string, string][] = [
    ["Reference", item.reference_no],
    ["Status", paid ? "Paid" : item.status.charAt(0) + item.status.slice(1).toLowerCase()],
    ["Requested on", formatDateTimeZoned(item.created_at)],
  ];
  if (item.reviewed_at) rows.push(["Paid on", formatDateTimeZoned(item.reviewed_at)]);
  rows.push(["Withdrawn from wallet", eur(item.amount)]);
  if (Number(item.fee_amount) > 0) rows.push(["Processing fee", `- ${eur(item.fee_amount)}`]);
  rows.push(["Net amount", eur(item.net_amount)]);
  if (item.conversion_rate) rows.push(["Conversion rate", `1 EUR = ${Number(item.conversion_rate).toFixed(4)} ${item.payout_currency}`]);
  rows.push(["Amount sent", payout]);
  rows.push(["Sent to", item.account_line]);
  if (item.payment_reference) rows.push(["Payment reference", item.payment_reference]);

  return (
    <div className="print-sheet">
      <style>{`
        @page { size: A4; margin: 16mm; }
        @media print {
          .no-print { display: none !important; }
          html, body { background: #ffffff !important; }
          .print-sheet { max-width: none; padding: 0; }
          .print-sheet > * { break-inside: avoid; }
        }
        .print-sheet {
          background: #ffffff; color: #0f172a; font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
          max-width: 720px; margin: 0 auto; padding: 32px 24px;
        }
        .print-sheet table { width: 100%; border-collapse: collapse; }
        .print-sheet td { padding: 9px 12px; font-size: 13px; border-bottom: 1px solid #e2e8f0; }
        .print-sheet td.label { color: #64748b; white-space: nowrap; }
        .print-sheet td.value { text-align: right; color: #0f172a; font-weight: 600; }
        .print-sheet .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
      `}</style>

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 24 }}>
        {logo ? (
          <img src={logo} alt={brand} style={{ height: 40, width: "auto", maxWidth: 200, objectFit: "contain" }} />
        ) : (
          <span style={{ fontSize: 22, fontWeight: 800 }}>{brand}</span>
        )}
        <span style={{ fontSize: 12, color: "#64748b" }}>Withdrawal receipt</span>
      </div>

      <h1 style={{ fontSize: 20, margin: "0 0 4px 0" }}>
        {paid ? "Payment sent" : "Withdrawal request"}
      </h1>
      <p className="mono" style={{ margin: "0 0 24px 0", fontSize: 13, color: "#64748b" }}>{item.reference_no}</p>

      {paid && (
        <div style={{ background: "#ecfdf5", borderLeft: "3px solid #059669", borderRadius: 8, padding: "14px 16px", marginBottom: 24 }}>
          <p style={{ margin: 0, fontSize: 11, textTransform: "uppercase", letterSpacing: 0.5, color: "#047857", fontWeight: 700 }}>Amount sent</p>
          <p style={{ margin: "4px 0 0 0", fontSize: 24, fontWeight: 800, color: "#065f46" }}>{payout}</p>
        </div>
      )}

      <table>
        <tbody>
          {rows.map(([label, value]) => (
            <tr key={label}>
              <td className="label">{label}</td>
              <td className={`value${label === "Reference" || label === "Payment reference" ? " mono" : ""}`}>{value}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {item.note && (
        <div style={{ border: "1px solid #e2e8f0", borderRadius: 12, padding: 16, marginTop: 20 }}>
          <p style={{ margin: "0 0 4px 0", fontSize: 11, textTransform: "uppercase", letterSpacing: 0.5, color: "#64748b", fontWeight: 700 }}>Note</p>
          <p style={{ margin: 0, fontSize: 13 }}>{item.note}</p>
        </div>
      )}

      <p style={{ marginTop: 24, fontSize: 11, color: "#64748b", lineHeight: 1.7 }}>
        The conversion rate shown is the rate at the moment this payout was approved and is stored with the request, so this
        receipt will always show the same figures.
        {settings.support_email ? ` Questions about this payment: ${settings.support_email}.` : ""}
      </p>

      <div className="no-print" style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 24 }}>
        <button
          onClick={() => window.print()}
          style={{ background: "#4f46e5", color: "#fff", border: 0, borderRadius: 10, padding: "10px 18px", fontSize: 13, fontWeight: 700, cursor: "pointer" }}
        >
          Print / Save as PDF
        </button>
        <a href="/wallet/withdraw" style={{ color: "#4f46e5", fontSize: 13, alignSelf: "center", textDecoration: "none" }}>
          Back to withdrawals
        </a>
      </div>
    </div>
  );
}
