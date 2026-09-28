"use client";

import React, { useState } from "react";
import { Check, Copy } from "lucide-react";

export type MerchantTab = "overview" | "provision" | "orders" | "commission" | "statement" | "api";

const STATUS_STYLES: Record<string, string> = {
  COMPLETED: "bg-emerald-50 text-emerald-700 border-emerald-200",
  FAILED: "bg-rose-50 text-rose-700 border-rose-200",
  PROCESSING: "bg-amber-50 text-amber-700 border-amber-200",
  PAID: "bg-amber-50 text-amber-700 border-amber-200",
  PENDING: "bg-gray-50 text-slate-600 border-gray-200",
  CANCELLED: "bg-gray-50 text-slate-500 border-gray-200",
};

const STATUS_LABELS: Record<string, string> = {
  COMPLETED: "Completed",
  FAILED: "Failed · refunded",
  PROCESSING: "Setting up",
  PAID: "Setting up",
  PENDING: "Awaiting payment",
  CANCELLED: "Cancelled",
};

export function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`inline-flex items-center text-[10px] font-bold px-2 py-0.5 rounded-full border whitespace-nowrap ${STATUS_STYLES[status] || STATUS_STYLES.PENDING}`}>
      {STATUS_LABELS[status] || status}
    </span>
  );
}

export function SourceBadge({ source }: { source: "api" | "web" | string }) {
  return source === "api" ? (
    <span className="text-[10px] font-bold px-2 py-0.5 rounded-full border bg-brand-50 text-brand-700 border-brand-200">API</span>
  ) : (
    <span className="text-[10px] font-bold px-2 py-0.5 rounded-full border bg-gray-50 text-slate-600 border-gray-200">Web</span>
  );
}

// Re-exported so the merchant components keep importing it from here,
// while the Bangladesh-time rule lives in one place.
export { formatDateTime } from "@/lib/datetime";

export function dataLabel(product?: { is_unlimited?: boolean; data_amount_gb?: number | null } | null) {
  if (!product) return "";
  if (product.is_unlimited || !product.data_amount_gb) return "Unlimited";
  return `${Number(product.data_amount_gb)} GB`;
}

export function CopyButton({ value, label = "Copy" }: { value: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={() => {
        navigator.clipboard.writeText(value);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }}
      className="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-1 rounded-lg border border-gray-200 bg-white hover:bg-gray-50 text-slate-600 shrink-0"
    >
      {copied ? <Check className="w-3 h-3 text-emerald-600" /> : <Copy className="w-3 h-3" />}
      {copied ? "Copied" : label}
    </button>
  );
}

export function Panel({
  title,
  description,
  actions,
  children,
  className = "",
}: {
  title?: string;
  description?: string;
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={`glass-panel rounded-2xl p-6 border border-gray-200 ${className}`}>
      {(title || actions) && (
        <div className="flex items-start justify-between gap-3 mb-4">
          <div>
            {title && <h3 className="text-base font-bold text-slate-900">{title}</h3>}
            {description && <p className="text-xs text-slate-500 mt-0.5">{description}</p>}
          </div>
          {actions}
        </div>
      )}
      {children}
    </div>
  );
}

export function getToken() {
  try {
    return localStorage.getItem("esim_token");
  } catch {
    return null;
  }
}
