const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function fetchApi(endpoint: string, options: RequestInit = {}) {
  const res = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || "API request failed");
  }
  return res.json();
}

export const api = {
  // Public
  getPublicSettings: () => fetchApi("/api/v1/settings/public"),
  getLanguages: () => fetchApi("/api/v1/settings/languages"),
  getRates: () => fetchApi("/api/v1/settings/rates"),
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

  // Wallets
  getMyWallets: (token: string) => fetchApi("/api/v1/wallets/my-wallets", { headers: { Authorization: `Bearer ${token}` } }),
  getMyLedger: (token: string) => fetchApi("/api/v1/wallets/ledger", { headers: { Authorization: `Bearer ${token}` } }),
  submitManualDeposit: (token: string, data: any) => fetchApi("/api/v1/wallets/manual-deposit", { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(data) }),

  // Orders
  checkout: (token: string, data: any) => fetchApi("/api/v1/orders/checkout", { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(data) }),
  getMyESIMs: (token: string) => fetchApi("/api/v1/orders/my-esims", { headers: { Authorization: `Bearer ${token}` } }),

  // Admin
  getAdminStats: (token: string) => fetchApi("/api/v1/admin/stats", { headers: { Authorization: `Bearer ${token}` } }),
  syncCatalog: (token: string) => fetchApi("/api/v1/admin/catalog/sync", { method: "POST", headers: { Authorization: `Bearer ${token}` } }),
  getMerchantQueue: (token: string) => fetchApi("/api/v1/admin/merchants/queue", { headers: { Authorization: `Bearer ${token}` } }),
  approveMerchant: (token: string, id: string) => fetchApi(`/api/v1/admin/merchants/${id}/approve`, { method: "POST", headers: { Authorization: `Bearer ${token}` } }),
  getPaymentQueue: (token: string) => fetchApi("/api/v1/admin/payments/manual-queue", { headers: { Authorization: `Bearer ${token}` } }),
  approvePayment: (token: string, id: string) => fetchApi(`/api/v1/admin/payments/manual/${id}/approve`, { method: "POST", headers: { Authorization: `Bearer ${token}` } }),
  updateBranding: (token: string, data: any) => fetchApi("/api/v1/admin/branding", { method: "PUT", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(data) }),
  overrideCurrency: (token: string, data: any) => fetchApi("/api/v1/admin/currencies/override", { method: "PUT", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(data) }),
  getAuditLogs: (token: string) => fetchApi("/api/v1/admin/audit-logs", { headers: { Authorization: `Bearer ${token}` } }),
  getSupplierLogs: (token: string) => fetchApi("/api/v1/admin/supplier-logs", { headers: { Authorization: `Bearer ${token}` } }),
};
