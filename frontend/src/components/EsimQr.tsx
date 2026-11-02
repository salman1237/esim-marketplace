"use client";

import React from "react";
import { QRCodeSVG } from "qrcode.react";
import { API_BASE } from "@/lib/api";
import { useAppSettings } from "@/lib/AppSettingsContext";

type Props = {
  value: string;
  size?: number;
  className?: string;
};

// Share of the QR's width the brand disc may cover. Kept in step with
// LOGO_RATIO in backend/app/services/qr_branding.py, which has tests that
// decode the result - the two should not drift apart, or the emailed code
// and the on-screen one stop behaving the same.
const LOGO_RATIO = 0.22;

/**
 * The eSIM QR with the Triptel mark in the middle.
 *
 * Every QR on the site goes through here so they are generated the same
 * way. Two things make the logo safe, and both are easy to lose by
 * editing a single call site, which is the reason this is one component
 * rather than six copies:
 *
 *   - level="H", ~30% error correction. These were level="M" (~15%)
 *     before any logo existed, which does not leave enough to cover the
 *     centre of the code.
 *   - excavate, which clears the modules behind the mark instead of
 *     painting over them, so the decoder is not fed half-covered modules.
 *
 * If no logo is configured the plain code is rendered. A customer who
 * cannot install their eSIM is a far worse outcome than an unbranded QR.
 */
export default function EsimQr({ value, size = 160, className = "" }: Props) {
  const { publicSettings } = useAppSettings();
  // The favicon first: it is the square mark. The main logo is a ~3:1
  // wordmark, and scaled into a small circle it becomes a few pixels tall
  // and unreadable - see the backend's _qr_mark_png, which picks the same
  // way so the emailed code and the on-screen one match.
  const logo = publicSettings?.favicon || publicSettings?.logo_light;
  const logoUrl = logo ? (logo.startsWith("http") ? logo : `${API_BASE}${logo}`) : null;
  const discSize = Math.round(size * LOGO_RATIO);

  return (
    <div className={`relative inline-flex items-center justify-center ${className}`}>
      <QRCodeSVG
        value={value}
        size={size}
        level="H"
        {...(logoUrl
          ? {
              imageSettings: {
                src: logoUrl,
                height: Math.round(discSize * 0.74),
                width: Math.round(discSize * 0.74),
                excavate: true,
              },
            }
          : {})}
      />
      {logoUrl && (
        // The white disc sits under the mark so the cleared square reads as
        // a circle. Purely cosmetic: the code is already valid without it.
        <span
          aria-hidden
          className="absolute rounded-full bg-white pointer-events-none"
          style={{ width: discSize, height: discSize }}
        />
      )}
      {logoUrl && (
        <img
          src={logoUrl}
          alt=""
          aria-hidden
          className="absolute rounded-full object-contain pointer-events-none"
          style={{ width: Math.round(discSize * 0.74), height: Math.round(discSize * 0.74) }}
        />
      )}
    </div>
  );
}
