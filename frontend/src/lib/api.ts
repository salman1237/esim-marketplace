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

export type SalesReportParams = {
  date_from?: string;
  date_to?: string;
  status?: string;
  q?: string;
  plan?: string;
  validity?: string;
  channel?: string;
  country?: string;
  sort?: string;
  direction?: "asc" | "desc";
  limit?: number;
  offset?: number;
};

function salesReportQuery(params: SalesReportParams): string {
  const qs = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") qs.append(key, String(value));
  });
  return qs.toString();
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
  // Country page by slug or ISO2 - /explore/bangladesh and /explore/bd both work.
  getDestination: (slug: string) => fetchApi(`/api/v1/catalog/destinations/${encodeURIComponent(slug)}`),
  getTopupLimits: (token: string) => fetchApi("/api/v1/admin/topup-limits", { headers: { Authorization: `Bearer ${token}` } }),
  updateTopupLimits: (token: string, data: { min: string; max: string }) => fetchApi("/api/v1/admin/topup-limits", { method: "PUT", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(data) }),

  // Auth
  register: (data: any) => fetchApi("/api/v1/auth/register", { method: "POST", body: JSON.stringify(data) }),
  login: (data: any) => fetchApi("/api/v1/auth/login", { method: "POST", body: JSON.stringify(data) }),
  googleLogin: (credential: string) => fetchApi("/api/v1/auth/google", { method: "POST", body: JSON.stringify({ credential }) }),
  forgotPassword: (email: string) => fetchApi("/api/v1/auth/forgot-password", { method: "POST", body: JSON.stringify({ email }) }),
  resetPassword: (token: string, newPassword: string) => fetchApi("/api/v1/auth/reset-password", { method: "POST", body: JSON.stringify({ token, new_password: newPassword }) }),
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
    fetchApi(`/api/v1/payments/shurjopay/topup?amount=${amountUsd}`, { method: "POST", headers: { Authorization: `Bearer ${token}` } }),

  // Orders
  checkout: (token: string, data: any) => fetchApi("/api/v1/orders/checkout", { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(data) }),
  initiateOrderPayment: (token: string, productId: string) => fetchApi("/api/v1/payments/shurjopay/order-initiate", { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ product_id: productId, payment_method: "SHURJOPAY" }) }),
  getMyESIMs: (token: string) => fetchApi("/api/v1/orders/my-esims", { headers: { Authorization: `Bearer ${token}` } }),
  getOrder: (token: string, orderId: string) => fetchApi(`/api/v1/orders/${orderId}`, { headers: { Authorization: `Bearer ${token}` } }),
  getResellerOrders: (token: string) => fetchApi("/api/v1/orders/reseller-orders", { headers: { Authorization: `Bearer ${token}` } }),

  // Merchant dashboard (approved merchants only)
  getMerchantOverview: (token: string) => fetchApi("/api/v1/merchant/overview", { headers: { Authorization: `Bearer ${token}` } }),
  getMerchantOrders: (token: string, params: { status?: string; source?: string; q?: string; limit?: number; offset?: number }) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== "") qs.append(key, String(value));
    });
    return fetchApi(`/api/v1/merchant/orders?${qs.toString()}`, { headers: { Authorization: `Bearer ${token}` } });
  },
  getMerchantOrder: (token: string, orderId: string) => fetchApi(`/api/v1/merchant/orders/${orderId}`, { headers: { Authorization: `Bearer ${token}` } }),
  transferCommission: (token: string, amount?: string) => fetchApi("/api/v1/merchant/commission/transfer", { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(amount ? { amount } : {}) }),
  getMerchantApiAccess: (token: string) => fetchApi("/api/v1/merchant/api-access", { headers: { Authorization: `Bearer ${token}` } }),
  setMerchantWebhook: (token: string, webhookUrl: string | null) => fetchApi("/api/v1/merchant/webhook-config", { method: "PUT", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ webhook_url: webhookUrl }) }),
  sendMerchantTestWebhook: (token: string) => fetchApi("/api/v1/merchant/webhook-test", { method: "POST", headers: { Authorization: `Bearer ${token}` } }),

  // Admin
  getAdminStats: (token: string) => fetchApi("/api/v1/admin/stats", { headers: { Authorization: `Bearer ${token}` } }),
  syncCatalog: (token: string) => fetchApi("/api/v1/admin/catalog/sync", { method: "POST", headers: { Authorization: `Bearer ${token}` } }),
  getMerchantQueue: (token: string) => fetchApi("/api/v1/admin/merchants/queue", { headers: { Authorization: `Bearer ${token}` } }),
  approveMerchant: (token: string, id: string) => fetchApi(`/api/v1/admin/merchants/${id}/approve`, { method: "POST", headers: { Authorization: `Bearer ${token}` } }),
  updateMerchantCommission: (token: string, id: string, ratePct: number) => fetchApi(`/api/v1/admin/merchants/${id}/commission`, { method: "PUT", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ rate_pct: ratePct }) }),
  getPartnerApiKeyStatus: (token: string, merchantId: string) => fetchApi(`/api/v1/admin/merchants/${merchantId}/api-key`, { headers: { Authorization: `Bearer ${token}` } }),
  generatePartnerApiKey: (token: string, merchantId: string) => fetchApi(`/api/v1/admin/merchants/${merchantId}/api-key`, { method: "POST", headers: { Authorization: `Bearer ${token}` } }),
  revokePartnerApiKey: (token: string, merchantId: string) => fetchApi(`/api/v1/admin/merchants/${merchantId}/api-key`, { method: "DELETE", headers: { Authorization: `Bearer ${token}` } }),
  getCommissionTiers: (token: string) => fetchApi("/api/v1/admin/commission-tiers", { headers: { Authorization: `Bearer ${token}` } }),
  createCommissionTier: (token: string, minVolumeUsd: number, ratePct: number) => fetchApi("/api/v1/admin/commission-tiers", { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ min_volume_usd: minVolumeUsd, rate_pct: ratePct }) }),
  deleteCommissionTier: (token: string, id: string) => fetchApi(`/api/v1/admin/commission-tiers/${id}`, { method: "DELETE", headers: { Authorization: `Bearer ${token}` } }),
  getPaymentQueue: (token: string) => fetchApi("/api/v1/admin/payments/manual-queue", { headers: { Authorization: `Bearer ${token}` } }),
  approvePayment: (token: string, id: string) => fetchApi(`/api/v1/admin/payments/manual/${id}/approve`, { method: "POST", headers: { Authorization: `Bearer ${token}` } }),
  searchAdminCustomers: (token: string, q: string) => fetchApi(`/api/v1/admin/customers/search?q=${encodeURIComponent(q)}`, { headers: { Authorization: `Bearer ${token}` } }),
  rechargeCustomerWallet: (token: string, userId: string, amount: string, description?: string) => fetchApi(`/api/v1/admin/customers/${userId}/wallet/recharge`, { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ amount, description }) }),
  adminPurchaseEsimForCustomer: (token: string, userId: string, productId: string) => fetchApi(`/api/v1/admin/customers/${userId}/purchase-esim`, { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ product_id: productId }) }),
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
  getAdminCatalog: (token: string, opts?: { q?: string; country_iso?: string; is_active?: boolean; limit?: number; offset?: number }) => {
    const params = new URLSearchParams();
    if (opts?.q) params.append("q", opts.q);
    if (opts?.country_iso) params.append("country_iso", opts.country_iso);
    if (opts?.is_active !== undefined) params.append("is_active", String(opts.is_active));
    params.append("limit", String(opts?.limit ?? 100));
    params.append("offset", String(opts?.offset ?? 0));
    return fetchApi(`/api/v1/admin/catalog?${params.toString()}`, { headers: { Authorization: `Bearer ${token}` } });
  },
  updateAdminCatalogProduct: (token: string, id: string, data: any) => fetchApi(`/api/v1/admin/catalog/${id}`, { method: "PUT", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(data) }),
  getShurjoPayConfig: (token: string) => fetchApi("/api/v1/admin/payment-gateways/shurjopay", { headers: { Authorization: `Bearer ${token}` } }),
  updateShurjoPayConfig: (token: string, data: { mode: string; username: string; password?: string; prefix: string }) => fetchApi("/api/v1/admin/payment-gateways/shurjopay", { method: "PUT", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(data) }),
  resetShurjoPayConfig: (token: string) => fetchApi("/api/v1/admin/payment-gateways/shurjopay", { method: "DELETE", headers: { Authorization: `Bearer ${token}` } }),
  testShurjoPayConfig: (token: string, data?: { mode: string; username: string; password?: string; prefix: string }) => fetchApi("/api/v1/admin/payment-gateways/shurjopay/test", { method: "POST", headers: { Authorization: `Bearer ${token}` }, ...(data ? { body: JSON.stringify(data) } : {}) }),
  getAdminPaymentMethods: (token: string) => fetchApi("/api/v1/admin/payment-methods", { headers: { Authorization: `Bearer ${token}` } }),
  updateAdminPaymentMethods: (token: string, methods: any[]) => fetchApi("/api/v1/admin/payment-methods", { method: "PUT", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ methods }) }),
  getFinanceSummary: (token: string, params: { date_from?: string; date_to?: string }) => fetchApi(`/api/v1/admin/finance/summary?${salesReportQuery(params)}`, { headers: { Authorization: `Bearer ${token}` } }),
  getVivapeReconciliation: (token: string, params: { date_from?: string; date_to?: string }) => fetchApi(`/api/v1/admin/finance/vivape?${salesReportQuery(params)}`, { headers: { Authorization: `Bearer ${token}` } }),
  getAdminMerchantStatement: (token: string, userId: string, month: string) => fetchApi(`/api/v1/admin/finance/merchant-statement?user_id=${encodeURIComponent(userId)}&month=${month}`, { headers: { Authorization: `Bearer ${token}` } }),
  getMyStatement: (token: string, month: string) => fetchApi(`/api/v1/merchant/statement?month=${month}`, { headers: { Authorization: `Bearer ${token}` } }),
  // Authenticated file download (CSV exports) - returns a Blob to save.
  downloadAuthed: async (token: string, path: string): Promise<Blob> => {
    const res = await fetch(`${API_BASE}${path}`, { headers: { Authorization: `Bearer ${token}` } });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || `Download failed with status ${res.status}`);
    }
    return res.blob();
  },
  getAdminLegalDocuments: (token: string) => fetchApi("/api/v1/admin/legal", { headers: { Authorization: `Bearer ${token}` } }),
  updateAdminLegalDocument: (token: string, slug: string, body: string) => fetchApi(`/api/v1/admin/legal/${slug}`, { method: "PUT", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ body }) }),
  getAdminPricing: (token: string) => fetchApi("/api/v1/admin/pricing", { headers: { Authorization: `Bearer ${token}` } }),
  updateAdminPricing: (token: string, sellingProfitPct: string) => fetchApi("/api/v1/admin/pricing", { method: "PUT", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ selling_profit_pct: sellingProfitPct }) }),
  getSalesBreakdown: (token: string, params: SalesReportParams) => fetchApi(`/api/v1/admin/reports/sales/breakdown?${salesReportQuery(params)}`, { headers: { Authorization: `Bearer ${token}` } }),
  getSalesReport: (token: string, params: SalesReportParams) => fetchApi(`/api/v1/admin/reports/sales?${salesReportQuery(params)}`, { headers: { Authorization: `Bearer ${token}` } }),
  downloadSalesReportCsv: async (token: string, params: SalesReportParams): Promise<Blob> => {
    const res = await fetch(`${API_BASE}/api/v1/admin/reports/sales.csv?${salesReportQuery(params)}`, { headers: { Authorization: `Bearer ${token}` } });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || `Export failed with status ${res.status}`);
    }
    return res.blob();
  },
  getAdminUsers: (token: string, q?: string) => fetchApi(`/api/v1/admin/users${q ? `?q=${encodeURIComponent(q)}` : ""}`, { headers: { Authorization: `Bearer ${token}` } }),
  makeUserReseller: (token: string, userId: string, data: { business_name: string; contact_phone: string; commission_rate_pct?: number }) => fetchApi(`/api/v1/admin/users/${userId}/make-reseller`, { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(data) }),
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
