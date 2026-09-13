"use client";

import React from "react";
import Link from "next/link";
import { Wifi } from "lucide-react";
import { API_BASE } from "@/lib/api";
import { useAppSettings } from "@/lib/AppSettingsContext";

// The brand mark on the sign-in / sign-up / password pages: the uploaded
// logo from branding settings (server-rendered, so no flash), linking home.
// The generic icon is only a fallback for when no logo has been uploaded.
export default function AuthBrandMark() {
  const { publicSettings } = useAppSettings();
  const logo: string | undefined = publicSettings?.logo_light || undefined;
  const name: string = publicSettings?.platform_name || "Home";

  return (
    <Link href="/" aria-label={name} className="inline-flex justify-center mb-4">
      {logo ? (
        <img
          src={logo.startsWith("http") ? logo : `${API_BASE}${logo}`}
          alt={name}
          className="h-12 max-w-[200px] w-auto object-contain"
        />
      ) : (
        <span className="w-12 h-12 rounded-xl bg-brand-600 flex items-center justify-center">
          <Wifi className="w-6 h-6 text-white" />
        </span>
      )}
    </Link>
  );
}
