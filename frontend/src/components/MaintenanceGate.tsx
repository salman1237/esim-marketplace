"use client";

import React from "react";
import { Wrench } from "lucide-react";
import { usePathname } from "next/navigation";
import { useAppSettings } from "@/lib/AppSettingsContext";

const ADMIN_ROLES = new Set(["SUPER_ADMIN", "ADMIN"]);
// A customer standing in an airport with a tracking link from their delivery
// email needs their QR code whatever we are doing to the site. The page is
// read-only and its own token is the only way in, so it stays up.
const ALWAYS_AVAILABLE = ["/track/"];

export default function MaintenanceGate({ children }: { children: React.ReactNode }) {
  const { maintenanceMode, platformName, t } = useAppSettings();
  const pathname = usePathname() || "";

  const [isAdmin, setIsAdmin] = React.useState(false);
  React.useEffect(() => {
    try {
      setIsAdmin(ADMIN_ROLES.has(localStorage.getItem("esim_role") || ""));
    } catch {
      // localStorage unavailable — treat as non-admin, matches fail-closed
      // behavior for everything else that reads esim_role.
    }
  }, []);

  const exempt = ALWAYS_AVAILABLE.some((prefix) => pathname.startsWith(prefix));

  if (maintenanceMode && !isAdmin && !exempt) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center px-6 text-center">
        <div className="w-16 h-16 rounded-2xl bg-gradient-to-tr from-brand-600 to-accent-500 flex items-center justify-center mb-6">
          <Wrench className="w-8 h-8 text-white" />
        </div>
        <h1 className="text-2xl font-bold text-slate-900 mb-2">
          {platformName} — {t("common", "maintenance_title", "Down for maintenance")}
        </h1>
        <p className="text-sm text-slate-500 max-w-md">
          {t("common", "maintenance_body", "We're making some improvements and will be back shortly. Thanks for your patience.")}
        </p>
      </div>
    );
  }

  return <>{children}</>;
}
