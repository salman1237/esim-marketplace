"use client";

import React, { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { QRCodeSVG } from "qrcode.react";
import { api, API_BASE } from "@/lib/api";
import { esimInstallLinks } from "@/lib/esimInstall";

// Deliberately light and self-contained: this page exists to be printed or
// saved as a PDF, so it avoids the app chrome, dark panels and animations
// that waste ink and don't survive the print stylesheet.
export default function PrintEsimPage() {
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
      api.getMyESIMs(token),
      api.getPublicSettings().catch(() => ({})),
    ])
      .then(([esims, s]) => {
        const found = (esims || []).find((e: any) => e.id === id);
        if (!found) setNotFound(true);
        setItem(found || null);
        setSettings(s || {});
      })
      .catch(() => setNotFound(true))
      .finally(() => setLoading(false));
  }, [id]);

  // Only offer the print dialog once there's something on the page to print.
  useEffect(() => {
    if (item) {
      const t = setTimeout(() => window.print(), 600);
      return () => clearTimeout(t);
    }
  }, [item]);

  if (loading) {
    return <div style={{ padding: 48, fontFamily: "system-ui", color: "#475569" }}>Preparing your eSIM…</div>;
  }
  if (notFound || !item) {
    return (
      <div style={{ padding: 48, fontFamily: "system-ui", color: "#475569" }}>
        <p>That eSIM could not be found.</p>
        <a href="/my-esims" style={{ color: "#4f46e5" }}>Back to My eSIMs</a>
      </div>
    );
  }

  const install = esimInstallLinks(item.lpa_string);
  const logo = settings.logo_light
    ? (settings.logo_light.startsWith("http") ? settings.logo_light : `${API_BASE}${settings.logo_light}`)
    : null;
  const brand = settings.platform_name || "Triptel";
  const rows: [string, string][] = [
    ["Order ID", item.order_no],
    ["Product", item.product_title],
    ["ICCID", item.iccid || "—"],
    ["Data", item.is_unlimited ? "Unlimited" : `${item.data_amount_gb} GB`],
    ["Plan Validity", `${item.validity_days} Days`],
  ];
  if (item.expires_at) {
    rows.push(["Expires", new Date(item.expires_at).toLocaleDateString()]);
  }

  return (
    <div className="print-sheet">
      <style>{`
        @page { size: A4; margin: 16mm; }
        @media print { .no-print { display: none !important; } }
        .print-sheet {
          background: #ffffff; color: #0f172a; font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
          max-width: 720px; margin: 0 auto; padding: 32px 24px;
        }
        .print-sheet table { width: 100%; border-collapse: collapse; }
        .print-sheet td { padding: 9px 12px; font-size: 13px; border-bottom: 1px solid #e2e8f0; }
        .print-sheet td.label { color: #64748b; white-space: nowrap; }
        .print-sheet td.value { text-align: right; color: #0f172a; }
        .print-sheet .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
      `}</style>

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 24 }}>
        {logo ? (
          <img src={logo} alt={brand} style={{ height: 40, width: "auto", maxWidth: 200, objectFit: "contain" }} />
        ) : (
          <span style={{ fontSize: 22, fontWeight: 800 }}>{brand}</span>
        )}
        <span style={{ fontSize: 12, color: "#64748b" }}>eSIM Installation Details</span>
      </div>

      <h1 style={{ fontSize: 20, margin: "0 0 4px 0" }}>{item.product_title}</h1>
      <p style={{ margin: "0 0 24px 0", fontSize: 13, color: "#64748b" }}>
        Order {item.order_no}
      </p>

      <div style={{ display: "flex", gap: 28, alignItems: "flex-start", flexWrap: "wrap", marginBottom: 24 }}>
        <div style={{ border: "1px solid #e2e8f0", borderRadius: 12, padding: 16, textAlign: "center" }}>
          <QRCodeSVG value={item.qr_code_data || item.lpa_string || ""} size={180} level="M" />
          <p style={{ margin: "10px 0 0 0", fontSize: 11, color: "#64748b" }}>Scan with the phone that will use the eSIM</p>
        </div>
        <div style={{ flex: 1, minWidth: 260 }}>
          <table>
            <tbody>
              {rows.map(([label, value]) => (
                <tr key={label}>
                  <td className="label">{label}</td>
                  <td className={`value${label === "ICCID" ? " mono" : ""}`}>{value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div style={{ border: "1px solid #e2e8f0", borderRadius: 12, padding: 16, marginBottom: 20 }}>
        <p style={{ margin: "0 0 4px 0", fontSize: 11, textTransform: "uppercase", letterSpacing: 0.5, color: "#64748b", fontWeight: 700 }}>
          Activation Code (LPA)
        </p>
        <p className="mono" style={{ margin: 0, fontSize: 12, wordBreak: "break-all" }}>{item.lpa_string}</p>
      </div>

      <div style={{ background: "#eef2ff", borderLeft: "3px solid #4f46e5", borderRadius: 8, padding: "14px 16px", marginBottom: 24 }}>
        <p style={{ margin: "0 0 8px 0", fontSize: 13, fontWeight: 700, color: "#3730a3" }}>How to install</p>
        <ol style={{ margin: 0, paddingLeft: 18, fontSize: 12, lineHeight: 1.9, color: "#475569" }}>
          <li>Connect the phone to Wi-Fi.</li>
          <li><strong>iPhone:</strong> Settings › Cellular › Add eSIM › Use QR Code.</li>
          <li><strong>Android:</strong> Settings › Network &amp; Internet › SIMs › Add eSIM.</li>
          <li>Scan the QR code above, or enter the activation code manually.</li>
        </ol>
      </div>

      <div className="no-print" style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        <button
          onClick={() => window.print()}
          style={{ background: "#4f46e5", color: "#fff", border: 0, borderRadius: 10, padding: "10px 18px", fontSize: 13, fontWeight: 700, cursor: "pointer" }}
        >
          Print / Save as PDF
        </button>
        {install.ios && (
          <a href={install.ios} style={{ background: "#0f172a", color: "#fff", borderRadius: 10, padding: "10px 18px", fontSize: 13, fontWeight: 700, textDecoration: "none" }}>
            Install on iPhone
          </a>
        )}
        {install.android && (
          <a href={install.android} style={{ background: "#3ddc84", color: "#0f172a", borderRadius: 10, padding: "10px 18px", fontSize: 13, fontWeight: 700, textDecoration: "none" }}>
            Install on Android
          </a>
        )}
        <a href="/my-esims" style={{ color: "#4f46e5", fontSize: 13, alignSelf: "center", textDecoration: "none" }}>
          Back to My eSIMs
        </a>
      </div>
    </div>
  );
}
