// Universal "one tap install" links for an eSIM activation string. Both
// platforms accept the same GSMA LPA payload on a vendor-hosted link that
// opens the system eSIM installer directly - no QR scan, no typing:
//
//   iOS 17.4+   https://esimsetup.apple.com/esim_qrcode_provisioning?carddata=...
//   Android     https://esimsetup.android.com/esim_qrcode_provisioning?carddata=...
//               (rolled out January 2026, so device support is still uneven)
//
// Support isn't universal, which is why the QR code and copyable activation
// code stay alongside these buttons everywhere they appear. Mirrors
// backend/app/services/esim_links.py - keep the two in step.

export function esimInstallLinks(lpaString?: string | null): { ios: string | null; android: string | null } {
  const lpa = (lpaString || "").trim();
  if (!lpa.toUpperCase().startsWith("LPA:")) {
    return { ios: null, android: null };
  }
  // ':' and '$' are data inside the payload, not URL structure.
  const carddata = encodeURIComponent(lpa);
  return {
    ios: `https://esimsetup.apple.com/esim_qrcode_provisioning?carddata=${carddata}`,
    android: `https://esimsetup.android.com/esim_qrcode_provisioning?carddata=${carddata}`,
  };
}
