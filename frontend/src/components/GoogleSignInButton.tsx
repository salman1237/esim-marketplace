"use client";

import React, { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useAppSettings } from "@/lib/AppSettingsContext";

declare global {
  interface Window {
    google?: any;
  }
}

const GSI_SRC = "https://accounts.google.com/gsi/client";

function loadGoogleIdentityServices(): Promise<void> {
  if (window.google?.accounts?.id) return Promise.resolve();
  return new Promise((resolve, reject) => {
    let script = document.querySelector<HTMLScriptElement>(`script[src="${GSI_SRC}"]`);
    if (!script) {
      script = document.createElement("script");
      script.src = GSI_SRC;
      script.async = true;
      script.defer = true;
      document.head.appendChild(script);
    }
    script.addEventListener("load", () => resolve());
    script.addEventListener("error", () => reject(new Error("gsi_load_failed")));
  });
}

type Props = {
  mode?: "signin" | "signup";
  // Also show Google's "Continue as ..." One Tap prompt.
  oneTap?: boolean;
};

// Google's own rendered button (required by Google's branding rules) plus
// One Tap. Google hands us a signed ID token; the backend verifies it and
// returns a normal Triptel session. Renders nothing until an OAuth client
// ID is configured on the backend.
export default function GoogleSignInButton({ mode = "signin", oneTap = false }: Props) {
  const { publicSettings, lang } = useAppSettings();
  const clientId: string | undefined = publicSettings?.google_client_id || undefined;
  const containerRef = useRef<HTMLDivElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!clientId) return;
    let cancelled = false;

    const handleCredential = async (response: { credential?: string }) => {
      if (!response?.credential) {
        setError("Google sign-in was cancelled.");
        return;
      }
      setBusy(true);
      setError("");
      try {
        const res = await api.googleLogin(response.credential);
        localStorage.setItem("esim_token", res.access_token);
        localStorage.setItem("esim_role", res.role);
        if (res.role === "SUPER_ADMIN" || res.role === "ADMIN") {
          window.location.href = "/admin";
          return;
        }
        // Same "Buy Now while signed out" resume path the email login and
        // register forms use - Google is just another way to finish it.
        const next = new URLSearchParams(window.location.search).get("next");
        window.location.href = next || "/";
      } catch (err: any) {
        setError(err.message || "Google sign-in failed. Please try again.");
        setBusy(false);
      }
    };

    loadGoogleIdentityServices()
      .then(() => {
        const container = containerRef.current;
        if (cancelled || !container || !window.google?.accounts?.id) return;
        window.google.accounts.id.initialize({
          client_id: clientId,
          callback: handleCredential,
          ux_mode: "popup",
          auto_select: false,
          cancel_on_tap_outside: true,
          context: mode === "signup" ? "signup" : "signin",
          itp_support: true,
          use_fedcm_for_prompt: true,
        });
        container.innerHTML = "";
        window.google.accounts.id.renderButton(container, {
          type: "standard",
          theme: "outline",
          size: "large",
          shape: "pill",
          text: mode === "signup" ? "signup_with" : "continue_with",
          logo_alignment: "center",
          // Match the site's selected language - otherwise Google uses the
          // browser's, e.g. a Bengali button on an English page.
          locale: lang,
          width: Math.min(400, Math.max(220, container.offsetWidth || 320)),
        });
        if (oneTap) window.google.accounts.id.prompt();
      })
      .catch(() => {
        if (!cancelled) setError("Couldn't load Google sign-in. Please use your email instead.");
      });

    return () => {
      cancelled = true;
      window.google?.accounts?.id?.cancel?.();
    };
  }, [clientId, mode, oneTap, lang]);

  if (!clientId) return null;

  return (
    <div className="mb-5">
      <div ref={containerRef} className="flex justify-center min-h-[44px]" aria-busy={busy} />
      {busy && <p className="text-[11px] text-slate-500 text-center mt-2">Signing you in with Google…</p>}
      {error && <p className="text-[11px] text-rose-600 text-center mt-2">{error}</p>}
      <div className="flex items-center gap-3 mt-5">
        <div className="h-px flex-1 bg-gray-200" />
        <span className="text-[11px] text-slate-400 uppercase tracking-wider">or use your email</span>
        <div className="h-px flex-1 bg-gray-200" />
      </div>
    </div>
  );
}
