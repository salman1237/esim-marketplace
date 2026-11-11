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
  // A code, or the special values ANY (every discounted sale) / NONE.
  discount_code?: string;
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
  getAdminDashboard: (token: string, days: number) => fetchApi(`/api/v1/admin/dashboard?days=${days}`, { headers: { Authorization: `Bearer ${token}` } }),
  getTopupLimits: (token: string) => fetchApi("/api/v1/admin/topup-limits", { headers: { Authorization: `Bearer ${token}` } }),
  updateTopupLimits: (token: string, data: { min: string; max: string }) => fetchApi("/api/v1/admin/topup-limits", { method: "PUT", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(data) }),

  // Auth
  register: (data: any) => fetchApi("/api/v1/auth/register", { method: "POST", body: JSON.stringify(data) }),
  login: (data: any) => fetchApi("/api/v1/auth/login", { method: "POST", body: JSON.stringify(data) }),
  googleLogin: (credential: string) => fetchApi("/api/v1/auth/google", { method: "POST", body: JSON.stringify({ credential }) }),
  forgotPassword: (email: string) => fetchApi("/api/v1/auth/forgot-password", { method: "POST", body: JSON.stringify({ email }) }),
  resetPassword: (token: string, newPassword: string) => fetchApi("/api/v1/auth/reset-password", { method: "POST", body: JSON.stringify({ token, new_password: newPassword }) }),
  getMe: (token: string) => fetchApi("/api/v1/auth/me", { headers: { Authorization: `Bearer ${token}` } }),
  // Persists the currency this account thinks in, so it follows the customer
  // between devices and drives what the top-up box asks them to type.
  updateMyPreferences: (token: string, preferredCurrency: string) =>
    fetchApi("/api/v1/auth/me/preferences", { method: "PUT", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ preferred_currency: preferredCurrency }) }),
  // An empty string clears the number; omitting the field leaves it alone.
  updateMyPhone: (token: string, phone: string) =>
    fetchApi("/api/v1/auth/me/preferences", { method: "PUT", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ phone }) }),
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

  // Withdrawals — limits, fee and eligibility all come from /config, so the
  // page never shows a button that the API is going to refuse.
  getWithdrawalConfig: (token: string) => fetchApi("/api/v1/withdrawals/config", { headers: { Authorization: `Bearer ${token}` } }),
  getPayoutAccounts: (token: string) => fetchApi("/api/v1/withdrawals/accounts", { headers: { Authorization: `Bearer ${token}` } }),
  addPayoutAccount: (token: string, data: any) => fetchApi("/api/v1/withdrawals/accounts", { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(data) }),
  setDefaultPayoutAccount: (token: string, id: string) => fetchApi(`/api/v1/withdrawals/accounts/${id}/default`, { method: "POST", headers: { Authorization: `Bearer ${token}` } }),
  deletePayoutAccount: (token: string, id: string) => fetchApi(`/api/v1/withdrawals/accounts/${id}`, { method: "DELETE", headers: { Authorization: `Bearer ${token}` } }),
  getMyWithdrawals: (token: string) => fetchApi("/api/v1/withdrawals", { headers: { Authorization: `Bearer ${token}` } }),
  getWithdrawal: (token: string, id: string) => fetchApi(`/api/v1/withdrawals/${id}`, { headers: { Authorization: `Bearer ${token}` } }),
  createWithdrawal: (token: string, data: { amount: string; bank_account_id: string; note_category?: string; note?: string }) =>
    fetchApi("/api/v1/withdrawals", { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(data) }),
  cancelWithdrawal: (token: string, id: string) => fetchApi(`/api/v1/withdrawals/${id}/cancel`, { method: "POST", headers: { Authorization: `Bearer ${token}` } }),

  // Payments
  // `amount` is in `currency` — the customer's own. The server converts to
  // EUR for the limits and to BDT for the gateway.
  initiateShurjopayTopup: (token: string, amount: number, currency?: string) =>
    fetchApi(`/api/v1/payments/shurjopay/topup?amount=${amount}${currency ? `&currency=${encodeURIComponent(currency)}` : ""}`, { method: "POST", headers: { Authorization: `Bearer ${token}` } }),

  // Agent portal. Gated on an approved agent profile, not on the role —
  // an agent can also be a merchant.
  getAgentStatus: (token: string) => fetchApi("/api/v1/agent/status", { headers: { Authorization: `Bearer ${token}` } }),
  applyAsAgent: (token: string, data: { company_name: string; contact_phone: string }) =>
    fetchApi("/api/v1/agent/apply", { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(data) }),
  getAgentOverview: (token: string) => fetchApi("/api/v1/agent/overview", { headers: { Authorization: `Bearer ${token}` } }),
  getAgentMerchants: (token: string) => fetchApi("/api/v1/agent/merchants", { headers: { Authorization: `Bearer ${token}` } }),
  addAgentMerchant: (token: string, merchant: string) =>
    fetchApi("/api/v1/agent/merchants", { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ merchant }) }),
  getAgentOrders: (token: string, opts?: { limit?: number; offset?: number }) =>
    fetchApi(`/api/v1/agent/orders?limit=${opts?.limit ?? 100}&offset=${opts?.offset ?? 0}`, { headers: { Authorization: `Bearer ${token}` } }),
  getAgentCommissionLedger: (token: string) => fetchApi("/api/v1/agent/commission-ledger", { headers: { Authorization: `Bearer ${token}` } }),
  getAgentStatement: (token: string, month: string) => fetchApi(`/api/v1/agent/statement?month=${month}`, { headers: { Authorization: `Bearer ${token}` } }),
  transferAgentCommission: (token: string) => fetchApi("/api/v1/agent/commission/transfer", { method: "POST", headers: { Authorization: `Bearer ${token}` } }),
  // Bonus = the share an agent takes out of a partner's commission. Requested
  // here, but only an admin approval makes it real.
  getAgentBonusRequests: (token: string) => fetchApi("/api/v1/agent/bonus-requests", { headers: { Authorization: `Bearer ${token}` } }),
  requestAgentBonus: (token: string, data: { merchant_profile_id: string; requested_pct: string; reason?: string }) =>
    fetchApi("/api/v1/agent/bonus-requests", { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(data) }),

  // Support tickets. Creating and replying use multipart because they carry
  // attachments, so they can't go through fetchApi's JSON default.
  getSupportCategories: () => fetchApi("/api/v1/support/categories"),
  getMyTickets: (token: string) => fetchApi("/api/v1/support/tickets", { headers: { Authorization: `Bearer ${token}` } }),
  getTicket: (token: string, id: string) => fetchApi(`/api/v1/support/tickets/${id}`, { headers: { Authorization: `Bearer ${token}` } }),
  createTicket: async (token: string, form: FormData) => {
    const res = await fetch(`${API_BASE}/api/v1/support/tickets`, {
      method: "POST", headers: { Authorization: `Bearer ${token}` }, body: form,
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `Failed with status ${res.status}`);
    return res.json();
  },
  replyToTicket: async (token: string, id: string, form: FormData) => {
    const res = await fetch(`${API_BASE}/api/v1/support/tickets/${id}/messages`, {
      method: "POST", headers: { Authorization: `Bearer ${token}` }, body: form,
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `Failed with status ${res.status}`);
    return res.json();
  },
  closeTicket: (token: string, id: string) => fetchApi(`/api/v1/support/tickets/${id}/close`, { method: "POST", headers: { Authorization: `Bearer ${token}` } }),
  // Attachments are behind auth, so they're fetched as a blob and handed back
  // as an object URL - same approach as KYC documents.
  getSupportAttachmentUrl: async (token: string, url: string) => {
    const res = await fetch(`${API_BASE}${url}`, { headers: { Authorization: `Bearer ${token}` } });
    if (!res.ok) throw new Error(`Failed to load attachment (${res.status})`);
    const blob = await res.blob();
    return { url: URL.createObjectURL(blob), contentType: blob.type };
  },
  // Staff
  getSupportQueue: (token: string, params: { status?: string; q?: string } = {}) => {
    const qs = new URLSearchParams();
    if (params.status) qs.append("status", params.status);
    if (params.q) qs.append("q", params.q);
    return fetchApi(`/api/v1/support/queue?${qs.toString()}`, { headers: { Authorization: `Bearer ${token}` } });
  },
  resolveTicket: (token: string, id: string) => fetchApi(`/api/v1/support/tickets/${id}/resolve`, { method: "POST", headers: { Authorization: `Bearer ${token}` } }),
  assignTicket: (token: string, id: string) => fetchApi(`/api/v1/support/tickets/${id}/assign`, { method: "POST", headers: { Authorization: `Bearer ${token}` } }),

  // Referrals. Reward credit lands in the REWARD wallet: spendable on
  // eSIMs, never withdrawable.
  validateReferralCode: (code: string) => fetchApi(`/api/v1/referrals/validate?code=${encodeURIComponent(code)}`),
  getMyReferrals: (token: string) => fetchApi("/api/v1/referrals/me", { headers: { Authorization: `Bearer ${token}` } }),
  claimReferralCode: (token: string, code: string) =>
    fetchApi("/api/v1/referrals/claim", { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ code }) }),

  // Discount codes — preview before paying; the real validation happens
  // again at checkout, under a row lock.
  previewDiscount: (token: string, code: string, productId: string) =>
    fetchApi("/api/v1/discounts/preview", { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ code, product_id: productId }) }),
  // No auth required - lets a visitor who isn't signed in yet see a code is
  // real before being asked to log in. checkout/preview still re-check for
  // real once a specific package and a specific account are both known.
  checkDiscountCode: (code: string) =>
    fetchApi("/api/v1/discounts/check", { method: "POST", body: JSON.stringify({ code }) }),

  // Orders
  checkout: (token: string, data: any) => fetchApi("/api/v1/orders/checkout", { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(data) }),
  // `extra` carries the buy-for-customer fields for merchants (is_buy_for_user,
  // beneficiary_email, auto_create_user) - same shape as the wallet checkout.
  initiateOrderPayment: (token: string, productId: string, extra: Record<string, any> = {}) => fetchApi("/api/v1/payments/shurjopay/order-initiate", { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ product_id: productId, payment_method: "SHURJOPAY", ...extra }) }),
  getMyESIMs: (token: string) => fetchApi("/api/v1/orders/my-esims", { headers: { Authorization: `Bearer ${token}` } }),
  // Live carrier telemetry for one eSIM. The GET is cache-backed; the POST
  // asks the carrier for fresh numbers and is cooled down server-side.
  getEsimStatus: (token: string, esimId: string) => fetchApi(`/api/v1/esims/${esimId}/status`, { headers: { Authorization: `Bearer ${token}` } }),
  // The tracking link from the delivery email — no auth, keyed on a random
  // share token rather than the eSIM id.
  getPublicEsimStatus: (shareToken: string) => fetchApi(`/api/v1/esims/public/${encodeURIComponent(shareToken)}`),
  refreshEsimStatus: (token: string, esimId: string) => fetchApi(`/api/v1/esims/${esimId}/refresh`, { method: "POST", headers: { Authorization: `Bearer ${token}` } }),
  // Adding data to an already-delivered eSIM - only ever has options for
  // an eSIM Access eSIM; an empty list is the ordinary answer otherwise.
  getTopupOptions: (token: string, esimId: string) => fetchApi(`/api/v1/esims/${esimId}/topup-options`, { headers: { Authorization: `Bearer ${token}` } }),
  purchaseTopup: (token: string, esimId: string, packageCode: string) =>
    fetchApi(`/api/v1/esims/${esimId}/topup`, { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ package_code: packageCode }) }),
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
  syncEsimAccessCatalog: (token: string) => fetchApi("/api/v1/admin/catalog/sync-esimaccess", { method: "POST", headers: { Authorization: `Bearer ${token}` } }),
  getEsimAccessBalance: (token: string) => fetchApi("/api/v1/admin/esimaccess/balance", { headers: { Authorization: `Bearer ${token}` } }),
  getEsimAccessWebhook: (token: string) => fetchApi("/api/v1/admin/esimaccess/webhook", { headers: { Authorization: `Bearer ${token}` } }),
  setEsimAccessWebhook: (token: string, webhookUrl?: string) =>
    fetchApi("/api/v1/admin/esimaccess/webhook", { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ webhook_url: webhookUrl || null }) }),
  // eSIM Access lifecycle actions - only meaningful for an esim.supplier === "esimaccess" eSIM.
  suspendEsim: (token: string, esimId: string) => fetchApi(`/api/v1/admin/esims/${esimId}/suspend`, { method: "POST", headers: { Authorization: `Bearer ${token}` } }),
  unsuspendEsim: (token: string, esimId: string) => fetchApi(`/api/v1/admin/esims/${esimId}/unsuspend`, { method: "POST", headers: { Authorization: `Bearer ${token}` } }),
  revokeEsim: (token: string, esimId: string) => fetchApi(`/api/v1/admin/esims/${esimId}/revoke`, { method: "POST", headers: { Authorization: `Bearer ${token}` } }),
  cancelEsim: (token: string, esimId: string) => fetchApi(`/api/v1/admin/esims/${esimId}/cancel`, { method: "POST", headers: { Authorization: `Bearer ${token}` } }),
  sendEsimSms: (token: string, esimId: string, message: string) =>
    fetchApi(`/api/v1/admin/esims/${esimId}/send-sms`, { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ message }) }),
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
  // Admin: agents
  getNotificationSettings: (token: string) => fetchApi("/api/v1/admin/notification-settings", { headers: { Authorization: `Bearer ${token}` } }),
  updateNotificationSettings: (token: string, email: string) => fetchApi("/api/v1/admin/notification-settings", { method: "PUT", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ system_notice_email: email }) }),
  sendTestEmail: (token: string, toEmail: string) => fetchApi("/api/v1/admin/notification-settings/test", { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ to_email: toEmail }) }),
  getSupplierSettings: (token: string) => fetchApi("/api/v1/admin/supplier-settings", { headers: { Authorization: `Bearer ${token}` } }),
  updateSupplierSettings: (token: string, enabledSuppliers: string[]) => fetchApi("/api/v1/admin/supplier-settings", { method: "PUT", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ enabled_suppliers: enabledSuppliers }) }),
  deductCustomerWallet: (token: string, userId: string, amount: string, reason: string, description?: string) =>
    fetchApi(`/api/v1/admin/customers/${userId}/wallet/deduct`, { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ amount, reason, description }) }),
  getCustomerWallet: (token: string, userId: string) =>
    fetchApi(`/api/v1/admin/customers/${userId}/wallet`, { headers: { Authorization: `Bearer ${token}` } }),
  changePassword: (token: string, currentPassword: string, newPassword: string) =>
    fetchApi("/api/v1/auth/change-password", { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }) }),
  getWalletReport: (token: string, query = "") =>
    fetchApi(`/api/v1/admin/reports/wallets${query ? `?${query}` : ""}`, { headers: { Authorization: `Bearer ${token}` } }),
  searchEsims: (token: string, query = "") =>
    fetchApi(`/api/v1/admin/esims/search${query ? `?${query}` : ""}`, { headers: { Authorization: `Bearer ${token}` } }),
  getEsimCounts: (token: string) =>
    fetchApi("/api/v1/admin/esims/counts", { headers: { Authorization: `Bearer ${token}` } }),
  getUnusedEsimsReport: (token: string, query = "") =>
    fetchApi(`/api/v1/admin/reports/unused-esims${query ? `?${query}` : ""}`, { headers: { Authorization: `Bearer ${token}` } }),
  getTestEsimIdentifiers: (token: string) =>
    fetchApi("/api/v1/admin/reports/test-identifiers", { headers: { Authorization: `Bearer ${token}` } }),
  updateTestEsimIdentifiers: (token: string, identifiers: string[]) =>
    fetchApi("/api/v1/admin/reports/test-identifiers", { method: "PUT", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ identifiers }) }),
  getAdminCountries: (token: string, search?: string) =>
    fetchApi(`/api/v1/admin/countries${search ? `?search=${encodeURIComponent(search)}` : ""}`, { headers: { Authorization: `Bearer ${token}` } }),
  updatePopularDestinations: (token: string, countries: { id: number; is_popular: boolean; popular_order: number }[]) =>
    fetchApi("/api/v1/admin/countries/popular", { method: "PUT", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ countries }) }),
  getSupplierAccount: (token: string, refresh = false) => fetchApi(`/api/v1/admin/supplier/account${refresh ? "?refresh=true" : ""}`, { headers: { Authorization: `Bearer ${token}` } }),
  getAdminAgents: (token: string, status?: string) => fetchApi(`/api/v1/admin/agents${status ? `?status=${status}` : ""}`, { headers: { Authorization: `Bearer ${token}` } }),
  getAgentMarginCheck: (token: string, merchantPct: string, agentPct: string) =>
    fetchApi(`/api/v1/admin/agents/margin-check?merchant_pct=${merchantPct}&agent_pct=${agentPct}`, { headers: { Authorization: `Bearer ${token}` } }),
  approveAgent: (token: string, id: string) => fetchApi(`/api/v1/admin/agents/${id}/approve`, { method: "POST", headers: { Authorization: `Bearer ${token}` } }),
  rejectAgent: (token: string, id: string, reason: string) => fetchApi(`/api/v1/admin/agents/${id}/reject?reason=${encodeURIComponent(reason)}`, { method: "POST", headers: { Authorization: `Bearer ${token}` } }),
  updateAgentCommission: (token: string, id: string, ratePct: string) =>
    fetchApi(`/api/v1/admin/agents/${id}/commission`, { method: "PUT", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ rate_pct: ratePct }) }),
  updateMerchantAgent: (token: string, merchantId: string, agentCode: string | null) =>
    fetchApi(`/api/v1/admin/merchants/${merchantId}/agent`, { method: "PUT", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(agentCode ? { agent_code: agentCode } : {}) }),

  getAdminAgentBonusRequests: (token: string, status?: string) => fetchApi(`/api/v1/admin/agent-bonus-requests${status ? `?status=${status}` : ""}`, { headers: { Authorization: `Bearer ${token}` } }),
  approveAgentBonus: (token: string, id: string, note?: string) => fetchApi(`/api/v1/admin/agent-bonus-requests/${id}/approve`, { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ note }) }),
  rejectAgentBonus: (token: string, id: string, note?: string) => fetchApi(`/api/v1/admin/agent-bonus-requests/${id}/reject`, { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ note }) }),
  requestKycReverification: (token: string, userId: string, reason: string) =>
    fetchApi("/api/v1/admin/kyc/request-reverification", { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ user_id: userId, reason }) }),

  // Admin: referral programme
  getAdminReferralSettings: (token: string) => fetchApi("/api/v1/admin/referral-settings", { headers: { Authorization: `Bearer ${token}` } }),
  updateAdminReferralSettings: (token: string, data: any) => fetchApi("/api/v1/admin/referral-settings", { method: "PUT", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(data) }),
  getAdminReferralReport: (token: string) => fetchApi("/api/v1/admin/referrals", { headers: { Authorization: `Bearer ${token}` } }),

  // Admin: discount codes
  getAdminDiscounts: (token: string) => fetchApi("/api/v1/admin/discounts", { headers: { Authorization: `Bearer ${token}` } }),
  createAdminDiscount: (token: string, data: any) => fetchApi("/api/v1/admin/discounts", { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(data) }),
  updateAdminDiscount: (token: string, id: string, data: any) => fetchApi(`/api/v1/admin/discounts/${id}`, { method: "PUT", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(data) }),
  deleteAdminDiscount: (token: string, id: string) => fetchApi(`/api/v1/admin/discounts/${id}`, { method: "DELETE", headers: { Authorization: `Bearer ${token}` } }),
  getAdminDiscountRedemptions: (token: string, id: string) => fetchApi(`/api/v1/admin/discounts/${id}/redemptions`, { headers: { Authorization: `Bearer ${token}` } }),

  // Admin: withdrawals
  getAdminWithdrawals: (token: string, status?: string) => fetchApi(`/api/v1/admin/withdrawals${status ? `?status=${status}` : ""}`, { headers: { Authorization: `Bearer ${token}` } }),
  getAdminWithdrawalSettings: (token: string) => fetchApi("/api/v1/admin/withdrawal-settings", { headers: { Authorization: `Bearer ${token}` } }),
  updateAdminWithdrawalSettings: (token: string, data: any) => fetchApi("/api/v1/admin/withdrawal-settings", { method: "PUT", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(data) }),
  // Multipart: the payment reference and the proof screenshot are both
  // required to mark a payout sent, so this can't go through fetchApi.
  approveWithdrawal: async (token: string, id: string, paymentReference: string, proof: File) => {
    const form = new FormData();
    form.append("payment_reference", paymentReference);
    form.append("proof", proof);
    const res = await fetch(`${API_BASE}/api/v1/admin/withdrawals/${id}/approve`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: form,
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || `Approval failed with status ${res.status}`);
    }
    return res.json();
  },
  rejectWithdrawal: (token: string, id: string, reason: string) => fetchApi(`/api/v1/admin/withdrawals/${id}/reject?reason=${encodeURIComponent(reason)}`, { method: "POST", headers: { Authorization: `Bearer ${token}` } }),
  getWithdrawalProofUrl: async (token: string, id: string) => {
    const res = await fetch(`${API_BASE}/api/v1/admin/withdrawals/${id}/proof`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) throw new Error(`Failed to load proof (${res.status})`);
    const blob = await res.blob();
    return { url: URL.createObjectURL(blob), contentType: blob.type };
  },
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
