"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight, Clock, Code2, LayoutDashboard, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";

export type PartnerState = "loading" | "guest" | "customer" | "pending" | "rejected" | "suspended" | "partner" | "staff";

// One /auth/me per token for every partner CTA on the page (the header
// already asks for it too), rather than a request per button.
let meCache: { token: string; promise: Promise<any> } | null = null;
function getMeCached(token: string) {
  if (!meCache || meCache.token !== token) {
    meCache = { token, promise: api.getMe(token).catch((e) => { meCache = null; throw e; }) };
  }
  return meCache.promise;
}

export function usePartnerStatus(): PartnerState {
  const [state, setState] = useState<PartnerState>("loading");
  useEffect(() => {
    let token: string | null = null;
    try {
      token = localStorage.getItem("esim_token");
    } catch {
      token = null;
    }
    if (!token) {
      setState("guest");
      return;
    }
    getMeCached(token)
      .then((me) => {
        const role = me?.role;
        const status = me?.merchant_profile?.status;
        if (role === "ADMIN" || role === "SUPER_ADMIN") setState("staff");
        else if (role === "MERCHANT" && status === "APPROVED") setState("partner");
        else if (status === "PENDING") setState("pending");
        else if (status === "REJECTED") setState("rejected");
        else if (status === "SUSPENDED") setState("suspended");
        else setState("customer");
      })
      .catch(() => setState("guest"));
  }, []);
  return state;
}

type Action = { label: string; href: string; icon?: React.ComponentType<{ className?: string }> };

type Props = {
  size?: "lg" | "sm";
  showNote?: boolean;
  // What a visitor who isn't a partner yet is pointed at: the application
  // itself on /partners, the /partners page from elsewhere on the site.
  guestPrimary?: Action;
  guestSecondary?: Action | null;
};

// The partner call-to-action, worded for who is looking: "Apply now" to a
// prospect, "Application under review" to an applicant, "Open Partner
// Portal" to an existing partner or staff - never "Apply" to someone who
// already is one.
export default function PartnerCta({
  size = "lg",
  showNote = false,
  guestPrimary = { label: "Apply now", href: "/reseller", icon: ArrowRight },
  guestSecondary = { label: "View API docs", href: "/api-docs", icon: Code2 },
}: Props) {
  const state = usePartnerStatus();
  const apiDocs: Action = { label: "View API docs", href: "/api-docs", icon: Code2 };

  const config: Record<Exclude<PartnerState, "loading">, { primary: Action; secondary: Action | null; note?: string }> = {
    guest: { primary: guestPrimary, secondary: guestSecondary },
    customer: { primary: guestPrimary, secondary: guestSecondary },
    pending: {
      primary: { label: "Application under review", href: "/reseller", icon: Clock },
      secondary: apiDocs,
      note: "We're reviewing your application and will email you when it's approved.",
    },
    rejected: {
      primary: { label: "View application status", href: "/reseller", icon: ArrowRight },
      secondary: null,
      note: "Your application wasn't approved. You can see the reason, or contact support.",
    },
    suspended: {
      primary: { label: "View account status", href: "/reseller", icon: ArrowRight },
      secondary: null,
      note: "Your partner access is suspended. Please contact support.",
    },
    partner: {
      primary: { label: "Open Partner Portal", href: "/reseller", icon: LayoutDashboard },
      secondary: apiDocs,
      note: "You're an approved partner — orders, commission and statements are in your Partner Portal.",
    },
    staff: {
      primary: { label: "Open Partner Portal", href: "/reseller", icon: LayoutDashboard },
      secondary: { label: "Review applications", href: "/admin", icon: ShieldCheck },
      note: "You're signed in as staff. Merchant applications are reviewed in the admin console.",
    },
  };

  const pad = size === "lg" ? "px-5 py-3 text-sm" : "px-4 py-2.5 text-xs";
  const iconCls = size === "lg" ? "w-4 h-4" : "w-3.5 h-3.5";

  if (state === "loading") {
    // Hold the space without guessing - a partner must never see "Apply now" flash.
    return <div className={`${size === "lg" ? "h-12 w-44" : "h-9 w-36"} rounded-xl bg-white/15 animate-pulse`} aria-hidden="true" />;
  }

  const { primary, secondary, note } = config[state];
  const PrimaryIcon = primary.icon;
  const SecondaryIcon = secondary?.icon;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-3">
        <Link href={primary.href} className={`inline-flex items-center justify-center gap-2 bg-white text-slate-900 hover:bg-white/90 font-bold rounded-xl ${pad}`}>
          {state === "pending" && PrimaryIcon && <PrimaryIcon className={iconCls} />}
          {primary.label}
          {state !== "pending" && PrimaryIcon && <PrimaryIcon className={iconCls} />}
        </Link>
        {size === "lg" && secondary && (
          <Link href={secondary.href} className={`inline-flex items-center justify-center gap-2 border border-white/30 hover:bg-white/10 font-bold rounded-xl ${pad}`}>
            {SecondaryIcon && <SecondaryIcon className={iconCls} />}
            {secondary.label}
          </Link>
        )}
      </div>
      {showNote && note && <p className="text-xs text-white/80 max-w-md">{note}</p>}
    </div>
  );
}
