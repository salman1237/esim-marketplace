export const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function fetchApi(endpoint: string, options: RequestInit = {}) {
  const url = endpoint.startsWith("http") ? endpoint : `${API_BASE}${endpoint}`;
  const headers = { "Content-Type": "application/json", ...options.headers };
  const res = await fetch(url, { ...options, headers });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || `Request failed with status ${res.status}`);
  }
  return res.json();
}

export const api = {
  // Public
  getPublicSettings: () => fetchApi("/api/v1/settings/public"),
  getLanguages: () => fetchApi("/api/v1/settings/languages"),
  getRates: () => fetchApi("/api/v1/settings/rates"),
  getTranslations: (lang: string) => fetchApi(`/api/v1/settings/translations/${lang}`),
  getCountries: (search?: string, popularOnly?: boolean) => {
    const params = new URLSearchParams();
    if (search) params.append("search", search);
    if (popularOnly) params.append("popular_only", "true");
    return fetchApi(`/api/v1/catalog/countries?${params.toString()}`);
  },
  getCountryProducts: (iso2: string) => fetchApi(`/api/v1/catalog/countries/${iso2}/products`),
  getProduct: (id: string) => fetchApi(`/api/v1/catalog/products/${id}`),

  // Auth
  register: (data: any) => fetchApi("/api/v1/auth/register", { method: "POST", body: JSON.stringify(data) }),
  login: (data: any) => fetchApi("/api/v1/auth/login", { method: "POST", body: JSON.stringify(data) }),
  getMe: (token: string) => fetchApi("/api/v1/auth/me", { headers: { Authorization: `Bearer ${token}` } }),
  applyMerchant: (token: string, data: any) => fetchApi("/api/v1/auth/apply-merchant", { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(data) }),
  getMyKyc: (token: string) => fetchApi("/api/v1/kyc/me", { headers: { Authorization: `Bearer ${token}` } }),
  submitKyc: async (token: string, nidNumber: string, front: File, back: File | null) => {
    const form = new FormData();
    form.append("nid_number", nidNumber);
    form.append("document_front", front);
    if (back) form.append("document_back", back);
    const res = await fetch(`${API_BASE}/api/v1/kyc/submit`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: form,
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || `Upload failed with status ${res.status}`);
    }
    return res.json();
  },

  // Wallets
  getMyWallets: (token: string) => fetchApi("/api/v1/wallets/my-wallets", { headers: { Authorization: `Bearer ${token}` } }),
  getMyLedger: (token: string) => fetchApi("/api/v1/wallets/ledger", { headers: { Authorization: `Bearer ${token}` } }),
  getWalletLedger: (token: string, type: string) => fetchApi(`/api/v1/wallets/ledger?wallet_type=${type}`, { headers: { Authorization: `Bearer ${token}` } }),
  submitManualDeposit: (token: string, data: any) => fetchApi("/api/v1/wallets/manual-deposit", { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(data) }),

  // Payments
  initiateShurjopayTopup: (token: string, amountUsd: number) =>
    fetchApi(`/api/v1/payments/shurjopay/topup?amount_usd=${amountUsd}`, { method: "POST", headers: { Authorization: `Bearer ${token}` } }),

  // Orders
  checkout: (token: string, data: any) => fetchApi("/api/v1/orders/checkout", { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(data) }),
  getMyESIMs: (token: string) => fetchApi("/api/v1/orders/my-esims", { headers: { Authorization: `Bearer ${token}` } }),
  getResellerOrders: (token: string) => fetchApi("/api/v1/orders/reseller-orders", { headers: { Authorization: `Bearer ${token}` } }),

  // Admin
  getAdminStats: (token: string) => fetchApi("/api/v1/admin/stats", { headers: { Authorization: `Bearer ${token}` } }),
  syncCatalog: (token: string) => fetchApi("/api/v1/admin/catalog/sync", { method: "POST", headers: { Authorization: `Bearer ${token}` } }),
  getMerchantQueue: (token: string) => fetchApi("/api/v1/admin/merchants/queue", { headers: { Authorization: `Bearer ${token}` } }),
  approveMerchant: (token: string, id: string) => fetchApi(`/api/v1/admin/merchants/${id}/approve`, { method: "POST", headers: { Authorization: `Bearer ${token}` } }),
  updateMerchantCommission: (token: string, id: string, ratePct: number) => fetchApi(`/api/v1/admin/merchants/${id}/commission`, { method: "PUT", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ rate_pct: ratePct }) }),
  getPaymentQueue: (token: string) => fetchApi("/api/v1/admin/payments/manual-queue", { headers: { Authorization: `Bearer ${token}` } }),
  approvePayment: (token: string, id: string) => fetchApi(`/api/v1/admin/payments/manual/${id}/approve`, { method: "POST", headers: { Authorization: `Bearer ${token}` } }),
  updateBranding: (token: string, data: any) => fetchApi("/api/v1/admin/branding", { method: "PUT", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(data) }),
  uploadBrandingAsset: async (token: string, kind: string, file: File) => {
    const form = new FormData();
    form.append("kind", kind);
    form.append("file", file);
    // No Content-Type header here on purpose — the browser sets
    // multipart/form-data with the correct boundary itself from the
    // FormData body; fetchApi's default JSON header would break the upload.
    const res = await fetch(`${API_BASE}/api/v1/admin/branding/upload`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: form,
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || `Upload failed with status ${res.status}`);
    }
    return res.json();
  },
  overrideCurrency: (token: string, data: any) => fetchApi("/api/v1/admin/currencies/override", { method: "PUT", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(data) }),
  getAuditLogs: (token: string) => fetchApi("/api/v1/admin/audit-logs", { headers: { Authorization: `Bearer ${token}` } }),
  getAuditLogsSummary: (token: string) => fetchApi("/api/v1/admin/audit-logs/summary", { headers: { Authorization: `Bearer ${token}` } }),
  getSupplierLogs: (token: string) => fetchApi("/api/v1/admin/supplier-logs", { headers: { Authorization: `Bearer ${token}` } }),
  
  // New Admin endpoints
  getAdminOrders: (token: string) => fetchApi("/api/v1/admin/orders", { headers: { Authorization: `Bearer ${token}` } }),
  getAdminCatalog: (token: string) => fetchApi("/api/v1/admin/catalog", { headers: { Authorization: `Bearer ${token}` } }),
  updateAdminCatalogProduct: (token: string, id: string, data: any) => fetchApi(`/api/v1/admin/catalog/${id}`, { method: "PUT", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(data) }),
  getAdminUsers: (token: string) => fetchApi("/api/v1/admin/users", { headers: { Authorization: `Bearer ${token}` } }),
  createStaffAccount: (token: string, data: any) => fetchApi("/api/v1/admin/users", { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(data) }),
  getKycQueue: (token: string) => fetchApi("/api/v1/admin/kyc/queue", { headers: { Authorization: `Bearer ${token}` } }),
  approveKyc: (token: string, id: string) => fetchApi(`/api/v1/admin/kyc/${id}/approve`, { method: "POST", headers: { Authorization: `Bearer ${token}` } }),
  rejectKyc: (token: string, id: string, reason: string) => fetchApi(`/api/v1/admin/kyc/${id}/reject?reason=${encodeURIComponent(reason)}`, { method: "POST", headers: { Authorization: `Bearer ${token}` } }),
  // Documents are behind auth (not the public uploads mount) - fetched as a
  // blob and handed back as an object URL for an <img>/<a> to point at.
  getKycDocumentUrl: async (token: string, submissionId: string, side: "front" | "back") => {
    const res = await fetch(`${API_BASE}/api/v1/admin/kyc/${submissionId}/document/${side}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) throw new Error(`Failed to load document (${res.status})`);
    const blob = await res.blob();
    return { url: URL.createObjectURL(blob), contentType: blob.type };
  },
  updateUserRole: (token: string, id: string, role: string) => fetchApi(`/api/v1/admin/users/${id}/role`, { method: "PUT", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ role }) }),
  updateUserStatus: (token: string, id: string, isActive: boolean) => fetchApi(`/api/v1/admin/users/${id}/status`, { method: "PUT", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ is_active: isActive }) }),

  // Super Admin: Languages & Translations
  getAllLanguages: (token: string) => fetchApi("/api/v1/admin/languages", { headers: { Authorization: `Bearer ${token}` } }),
  createLanguage: (token: string, data: any) => fetchApi("/api/v1/admin/languages", { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(data) }),
  toggleLanguage: (token: string, code: string, isActive: boolean) => fetchApi("/api/v1/admin/languages/toggle", { method: "PUT", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ code, is_active: isActive }) }),
  upsertTranslation: (token: string, data: any) => fetchApi("/api/v1/admin/translations", { method: "PUT", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(data) }),
  autoTranslateLanguage: (token: string, code: string) => fetchApi(`/api/v1/admin/languages/${code}/auto-translate`, { method: "POST", headers: { Authorization: `Bearer ${token}` } }),
};
