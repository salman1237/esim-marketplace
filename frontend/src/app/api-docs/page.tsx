"use client";

import React, { useState } from "react";
import Link from "next/link";
import { Copy, Check, Terminal, ArrowRight } from "lucide-react";

function CodeBlock({ children, label }: { children: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(children.trim());
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  return (
    <div className="rounded-xl overflow-hidden border border-gray-200 my-3">
      {label && (
        <div className="flex items-center justify-between px-4 py-2 bg-gray-50 border-b border-gray-200">
          <span className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">{label}</span>
        </div>
      )}
      <div className="relative bg-slate-900">
        <button
          onClick={copy}
          aria-label="Copy code"
          className="absolute top-2 end-2 p-1.5 rounded-lg bg-white/10 hover:bg-white/20 text-slate-300 hover:text-white transition-colors"
        >
          {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
        </button>
        <pre className="p-4 text-xs text-slate-100 overflow-x-auto whitespace-pre"><code>{children.trim()}</code></pre>
      </div>
    </div>
  );
}

function IC({ children }: { children: React.ReactNode }) {
  return <code className="text-[13px] bg-gray-100 text-brand-700 px-1.5 py-0.5 rounded font-mono">{children}</code>;
}

function Section({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
  return (
    <section id={id} className="glass-panel rounded-2xl border border-gray-200 p-6 sm:p-8 scroll-mt-24">
      <h2 className="text-xl font-bold text-slate-900 mb-4">{title}</h2>
      <div className="space-y-4 text-sm text-slate-600 leading-relaxed">{children}</div>
    </section>
  );
}

function Endpoint({ method, path, children }: { method: string; path: string; children: React.ReactNode }) {
  const methodColor: Record<string, string> = {
    GET: "bg-emerald-50 text-emerald-700 border-emerald-200",
    POST: "bg-brand-50 text-brand-700 border-brand-200",
    PUT: "bg-amber-50 text-amber-700 border-amber-200",
    DELETE: "bg-rose-50 text-rose-700 border-rose-200",
  };
  return (
    <div className="border-t border-gray-100 pt-6 mt-6 first:border-0 first:mt-0 first:pt-0">
      <div className="flex items-center gap-2 mb-3">
        <span className={`text-[11px] font-bold px-2 py-0.5 rounded border ${methodColor[method]}`}>{method}</span>
        <code className="text-sm font-mono text-slate-900">{path}</code>
      </div>
      <div className="space-y-3 text-sm text-slate-600 leading-relaxed">{children}</div>
    </div>
  );
}

const TOC = [
  { id: "auth", label: "1. Authentication" },
  { id: "endpoints", label: "2. Endpoints" },
  { id: "webhooks", label: "3. Webhooks" },
  { id: "rate-limits", label: "4. Rate Limits" },
  { id: "errors", label: "5. Errors" },
  { id: "getting-access", label: "6. Getting API Access" },
];

export default function ApiDocsPage() {
  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
      <div className="mb-8">
        <div className="inline-flex items-center space-x-1.5 text-brand-600 text-xs font-bold uppercase tracking-wider mb-2">
          <Terminal className="w-4 h-4" />
          <span>For Developers</span>
        </div>
        <h1 className="text-3xl font-extrabold text-slate-900">Partner Reseller API</h1>
        <p className="text-sm text-slate-500 mt-2 max-w-2xl">
          Browse the eSIM catalog, place orders on behalf of your own customers, and receive delivery
          confirmation from your own backend &mdash; no browser session required.
        </p>
        <div className="mt-4 flex items-center gap-2 text-xs">
          <span className="text-slate-500">Base URL</span>
          <code className="font-mono bg-gray-100 text-slate-900 px-2 py-1 rounded">https://triptel.co/api/v1/partner</code>
        </div>
      </div>

      {/* Quick nav */}
      <nav className="glass-panel rounded-2xl border border-gray-200 p-4 mb-8">
        <div className="flex flex-wrap gap-2">
          {TOC.map((item) => (
            <a
              key={item.id}
              href={`#${item.id}`}
              className="text-xs font-semibold px-3 py-1.5 rounded-lg bg-gray-50 hover:bg-gray-100 text-slate-700 transition-colors"
            >
              {item.label}
            </a>
          ))}
        </div>
      </nav>

      <div className="mb-8 p-4 rounded-xl bg-amber-50 border border-amber-200 text-xs text-amber-700">
        Getting set up is an admin-only, manual step: a Super Admin issues your API key once your merchant
        application is approved. There is no self-service signup for API access &mdash; see &sect;6 below.
      </div>

      <div className="space-y-6">
        <Section id="auth" title="1. Authentication">
          <p>
            All endpoints except the token endpoint itself require a <strong>Bearer access token</strong> in
            the <IC>Authorization</IC> header. The long-lived API key you were issued (<IC>esim_live_...</IC>)
            is <strong>never</strong> sent on these calls directly &mdash; it is only ever used once, to obtain a token.
          </p>

          <h3 className="text-sm font-bold text-slate-900 pt-2">1.1 Exchange your API key for an access token</h3>
          <Endpoint method="POST" path="/auth/token">
            <CodeBlock label="Request">{`POST /api/v1/partner/auth/token
Content-Type: application/json

{
  "api_key": "esim_live_1a2b3c4d5e6f7g8h..."
}`}</CodeBlock>
            <CodeBlock label="Response 200">{`{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 3600
}`}</CodeBlock>
            <ul className="list-disc ps-5 space-y-1.5">
              <li>Tokens are valid for <strong>1 hour</strong>. There is no refresh token &mdash; when a token expires, call this endpoint again with your API key to get a new one (standard OAuth2 Client Credentials style flow).</li>
              <li><IC>401</IC> if the key is invalid, malformed, or has been revoked.</li>
              <li>Rate limited to <strong>10 requests/minute per IP</strong>.</li>
            </ul>
          </Endpoint>

          <h3 className="text-sm font-bold text-slate-900 pt-4">1.2 Use the token on every other call</h3>
          <CodeBlock>{`GET /api/v1/partner/me
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...`}</CodeBlock>
          <ul className="list-disc ps-5 space-y-1.5">
            <li><IC>401</IC> if the token is missing, malformed, expired, or was issued for a different purpose &mdash; a regular customer login token cannot be used here, and this token cannot be used against the regular customer-facing API either.</li>
            <li>If your key is revoked by an admin, tokens already issued for it stop working on their very next use &mdash; you don&apos;t have to wait out the full hour.</li>
          </ul>

          <h3 className="text-sm font-bold text-slate-900 pt-4">Full flow example</h3>
          <CodeBlock label="bash">{`TOKEN=$(curl -s -X POST https://triptel.co/api/v1/partner/auth/token \\
  -H "Content-Type: application/json" \\
  -d '{"api_key": "esim_live_..."}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -s https://triptel.co/api/v1/partner/me \\
  -H "Authorization: Bearer $TOKEN"`}</CodeBlock>
        </Section>

        <Section id="endpoints" title="2. Endpoints">
          <p>All request/response bodies are JSON. Every endpoint below requires the Bearer token from &sect;1.2.</p>

          <Endpoint method="GET" path="/countries">
            <p>Lists all active destination countries. Optional query param <IC>search</IC> filters by name or ISO2 code.</p>
            <CodeBlock label="Response 200">{`[
  {
    "id": 1,
    "iso2": "US",
    "iso3": "USA",
    "name_en": "United States",
    "name_bn": null,
    "flag_url": "https://...",
    "region": null,
    "is_popular": true,
    "is_active": true
  }
]`}</CodeBlock>
            <p className="text-xs text-slate-500">Rate limit: 120/minute.</p>
          </Endpoint>

          <Endpoint method="GET" path="/countries/{iso2}/products">
            <p>Lists active eSIM data products for a country. <IC>iso2</IC> is case-insensitive.</p>
            <CodeBlock label="Response 200">{`[
  {
    "id": "a1b2c3d4-...",
    "country_id": 1,
    "title_en": "1GB / 7 Days",
    "title_bn": null,
    "data_amount_gb": 1.0,
    "validity_days": 7,
    "retail_price": 4.50,
    "currency": "USD",
    "is_unlimited": false,
    "is_active": true,
    "coverage_networks": null
  }
]`}</CodeBlock>
            <p className="text-xs text-slate-500"><IC>404</IC> if the country ISO2 doesn&apos;t exist. Rate limit: 120/minute.</p>
          </Endpoint>

          <Endpoint method="GET" path="/me">
            <p>Your merchant profile, effective commission rate, and current wallet balance.</p>
            <CodeBlock label="Response 200">{`{
  "business_name": "Acme Travel Co",
  "commission_rate_pct": 5.00,
  "wallet_balance": 142.5000,
  "wallet_currency": "USD",
  "commission_balance": 3.2500,
  "webhook_configured": true
}`}</CodeBlock>
            <p>
              <IC>wallet_balance</IC> is the prepaid balance orders are paid from &mdash; check it before charging your own
              customer. <IC>commission_balance</IC> is commission earned on completed orders, held separately.
            </p>
            <p className="text-xs text-slate-500">Reflects any active volume-based commission tier, falling back to your flat rate. Rate limit: 120/minute.</p>
          </Endpoint>

          <Endpoint method="POST" path="/orders">
            <p>
              Places an order and provisions an eSIM <strong>asynchronously</strong>. Your merchant wallet is
              debited the product&apos;s <IC>retail_price</IC> immediately; the order returns in{" "}
              <IC>PROCESSING</IC> status right away &mdash; poll <IC>GET /orders/{"{id}"}</IC> or wait for the
              webhook (&sect;3) to find out whether it completed.
            </p>
            <CodeBlock label="Request">{`{
  "product_id": "a1b2c3d4-...",
  "customer_reference": "your-internal-order-id-123"
}`}</CodeBlock>
            <p>The response is the full order object (see <IC>GET /orders/{"{order_id}"}</IC> below) plus <IC>idempotent_replay</IC>.</p>

            <p className="font-semibold text-slate-900">Always send customer_reference &mdash; it makes retries safe</p>
            <ul className="list-disc ps-5 space-y-1.5">
              <li>The <strong>same</strong> <IC>customer_reference</IC> with the same <IC>product_id</IC> returns the <strong>original</strong> order (<IC>{`"idempotent_replay": true`}</IC>) and <strong>never charges your wallet again</strong>.</li>
              <li>The same <IC>customer_reference</IC> with a different <IC>product_id</IC> returns <IC>409</IC>.</li>
              <li>Without one, every call is a new purchase &mdash; a retried timeout can buy two eSIMs. Use one unique value per eSIM you sell, e.g. your own order ID.</li>
            </ul>

            <p className="font-semibold text-slate-900">What happens after PROCESSING (usually 10&ndash;30 seconds):</p>
            <ul className="list-disc ps-5 space-y-1.5">
              <li><strong>Success</strong> &mdash; order becomes <IC>COMPLETED</IC>, the eSIM fields and install links are filled in, and commission is credited to your account.</li>
              <li><strong>Failure</strong> &mdash; order becomes <IC>FAILED</IC>, no eSIM is issued, and the full amount is refunded to your wallet automatically. No commission is paid on a failed order.</li>
              <li>If our server restarts mid-order, a recovery job still settles it within minutes &mdash; a <IC>PROCESSING</IC> order always ends as <IC>COMPLETED</IC> or <IC>FAILED</IC>.</li>
            </ul>
            <p className="text-xs text-slate-500"><IC>400</IC> insufficient wallet balance (nothing charged) &middot; <IC>404</IC> product not found/inactive &middot; <IC>409</IC> customer_reference reused for another product &middot; rate limit 30/minute.</p>
          </Endpoint>

          <Endpoint method="GET" path="/orders/{order_id}">
            <p>The current state of one of your orders. Poll every 3&ndash;5 seconds while <IC>PROCESSING</IC>. The webhook sends this same object.</p>
            <CodeBlock label="Response 200">{`{
  "order_id": "e5f6a7b8-...",
  "order_no": "PTR-20260913-A1B2C3",
  "customer_reference": "your-order-id-123",
  "status": "COMPLETED",
  "amount": "4.5000",
  "currency": "USD",
  "product": {
    "id": "a1b2c3d4-...",
    "title": "Singapore 1GB 7 Days",
    "country_iso2": "SG",
    "data_amount_gb": 1.0,
    "is_unlimited": false,
    "validity_days": 7
  },
  "iccid": "8965012345678901234",
  "lpa_string": "LPA:1$smdp.example.com$ABC123",
  "qr_code_data": "LPA:1$smdp.example.com$ABC123",
  "smdp_address": "smdp.example.com",
  "matching_id": "ABC123",
  "install_links": {
    "ios": "https://esimsetup.apple.com/esim_qrcode_provisioning?carddata=LPA%3A1%24...",
    "android": "https://esimsetup.android.com/esim_qrcode_provisioning?carddata=LPA%3A1%24..."
  },
  "is_mock_fallback": false,
  "created_at": "2026-09-13T10:00:00+00:00",
  "updated_at": "2026-09-13T10:00:14+00:00"
}`}</CodeBlock>
            <ul className="list-disc ps-5 space-y-1.5">
              <li>Encode <IC>qr_code_data</IC> into the QR code your customer scans; show <IC>smdp_address</IC> and <IC>matching_id</IC> for manual entry.</li>
              <li><IC>install_links.ios</IC> works on iOS 17.4+; Android support is still uneven &mdash; always show the QR code too.</li>
              <li>For unlimited plans <IC>is_unlimited</IC> is true and <IC>data_amount_gb</IC> is 0.</li>
              <li>Fields are only ever added, never removed or renamed &mdash; ignore ones you don&apos;t recognise. <IC>is_mock_fallback</IC> is legacy and always false.</li>
            </ul>
            <p className="text-xs text-slate-500"><IC>404</IC> if the order doesn&apos;t exist or isn&apos;t yours. Rate limit: 120/minute.</p>
          </Endpoint>

          <Endpoint method="GET" path="/orders">
            <p>
              Orders you placed through this API, newest first &mdash; for reconciliation. Query params:{" "}
              <IC>customer_reference</IC>, <IC>status</IC> (PROCESSING, COMPLETED, FAILED), <IC>limit</IC> (1&ndash;100,
              default 50), <IC>offset</IC>.
            </p>
            <CodeBlock label="Response 200">{`{
  "orders": [ { "order_id": "e5f6a7b8-...", "status": "COMPLETED", "...": "..." } ],
  "total": 1,
  "limit": 50,
  "offset": 0
}`}</CodeBlock>
            <p className="text-xs text-slate-500">Rate limit: 120/minute.</p>
          </Endpoint>

          <Endpoint method="PUT" path="/webhook-config">
            <p>Sets, rotates, or clears your webhook endpoint. Self-service &mdash; no admin involvement needed.</p>
            <CodeBlock label="Request (set/rotate)">{`{ "webhook_url": "https://yourapp.example.com/webhooks/esim" }`}</CodeBlock>
            <CodeBlock label="Response 200">{`{
  "webhook_url": "https://yourapp.example.com/webhooks/esim",
  "webhook_secret": "whsec_...",
  "warning": "Store this secret securely - it will not be shown again in full."
}`}</CodeBlock>
            <p>
              A <strong>new</strong> <IC>webhook_secret</IC> is generated every time you set or change the URL
              &mdash; save it immediately, it verifies webhook signatures (&sect;3) and is never shown again.
            </p>
            <p>Send <IC>{`{"webhook_url": null}`}</IC> to clear your webhook entirely (you&apos;ll only be able to poll after that):</p>
            <CodeBlock label="Response (clear)">{`{ "webhook_url": null, "webhook_secret": null }`}</CodeBlock>
            <p className="text-xs text-slate-500">Rate limit: 10/minute.</p>
          </Endpoint>
        </Section>

        <Section id="webhooks" title="3. Webhooks">
          <p>
            If you have a <IC>webhook_url</IC> configured, we POST to it once your order reaches a terminal
            state (<IC>COMPLETED</IC> or <IC>FAILED</IC>).
          </p>
          <p>
            <strong>Delivery attempts:</strong> one immediately when the order settles; if that fails (non-2xx
            response, 10-second timeout, connection error), a sweep every 5 minutes retries it, up to{" "}
            <strong>3 attempts total</strong> within 24 hours &mdash; for both <IC>COMPLETED</IC> and{" "}
            <IC>FAILED</IC> orders. Poll <IC>GET /orders/{"{order_id}"}</IC> if you suspect a delivery was missed.
          </p>

          <h3 className="text-sm font-bold text-slate-900 pt-2">Payload</h3>
          <p>
            The body is exactly the order object returned by <IC>GET /orders/{"{order_id}"}</IC> (&sect;2). On a{" "}
            <IC>FAILED</IC> order the eSIM fields are <IC>null</IC> &mdash; check <IC>status</IC> first.
          </p>

          <h3 className="text-sm font-bold text-slate-900 pt-2">Your receiver must</h3>
          <ul className="list-disc ps-5 space-y-1.5">
            <li>Verify the signature on the raw body (below) and reject mismatches with <IC>401</IC>.</li>
            <li>Be idempotent: the same order can arrive more than once, or race your own polling &mdash; key on <IC>order_id</IC>.</li>
            <li>Respond <IC>2xx</IC> quickly and do slow work afterwards.</li>
            <li>
              Check the <IC>X-Webhook-Event</IC> header: <IC>order.updated</IC> for orders, <IC>webhook.test</IC> for a
              signed test ping sent from your Partner Dashboard (body <IC>{`{"event": "webhook.test", ...}`}</IC>) &mdash;
              verify it and return <IC>2xx</IC> without processing.
            </li>
          </ul>
          <p>
            You can set, rotate, remove and test your webhook, and see every delivery attempt, from your{" "}
            <Link href="/reseller#api" className="font-semibold text-brand-600 hover:text-brand-700">Partner Dashboard</Link>.
          </p>

          <h3 className="text-sm font-bold text-slate-900 pt-4">Signature verification</h3>
          <p>
            Every delivery includes an <IC>X-Webhook-Signature</IC> header: the <strong>HMAC-SHA256</strong> of
            the exact raw request body, hex-encoded, using your <IC>webhook_secret</IC>.
          </p>
          <CodeBlock label="python">{`import hmac, hashlib

def verify_webhook(raw_body: bytes, signature_header: str, webhook_secret: str) -> bool:
    expected = hmac.new(webhook_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)`}</CodeBlock>
          <p>
            Always verify against the <strong>raw bytes</strong> of the request body, before any JSON parsing
            &mdash; re-serializing and re-hashing a parsed-then-reserialized payload is not guaranteed to match
            byte-for-byte.
          </p>
        </Section>

        <Section id="rate-limits" title="4. Rate Limits">
          <div className="overflow-x-auto">
            <table className="w-full text-start text-sm">
              <thead className="text-slate-500 border-b border-gray-200">
                <tr>
                  <th className="py-2 pe-4 font-semibold">Endpoint</th>
                  <th className="py-2 font-semibold">Limit</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                <tr><td className="py-2.5 pe-4"><IC>POST /auth/token</IC></td><td className="py-2.5">10/minute (per IP)</td></tr>
                <tr><td className="py-2.5 pe-4"><IC>POST /orders</IC></td><td className="py-2.5">30/minute (per API key)</td></tr>
                <tr><td className="py-2.5 pe-4"><IC>PUT /webhook-config</IC></td><td className="py-2.5">10/minute (per API key)</td></tr>
                <tr><td className="py-2.5 pe-4">Everything else</td><td className="py-2.5">120/minute (per API key)</td></tr>
              </tbody>
            </table>
          </div>
          <p>
            A <IC>429</IC> response means you&apos;ve hit the limit &mdash; back off and retry after a short
            delay. Limits are keyed to your specific API key (via the token), not your IP, except for the token
            endpoint itself (which has no partner identity yet).
          </p>
        </Section>

        <Section id="errors" title="5. Errors">
          <p>Standard HTTP status codes; error detail is always in the JSON body&apos;s <IC>detail</IC> field:</p>
          <CodeBlock>{`{ "detail": "Insufficient wallet balance. Please top up." }`}</CodeBlock>
          <div className="overflow-x-auto">
            <table className="w-full text-start text-sm">
              <thead className="text-slate-500 border-b border-gray-200">
                <tr>
                  <th className="py-2 pe-4 font-semibold">Status</th>
                  <th className="py-2 font-semibold">Meaning</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                <tr><td className="py-2.5 pe-4 font-mono">400</td><td className="py-2.5">Bad request &mdash; invalid input or a business rule violation</td></tr>
                <tr><td className="py-2.5 pe-4 font-mono">401</td><td className="py-2.5">Missing/invalid/expired token, or invalid/revoked API key at the token endpoint</td></tr>
                <tr><td className="py-2.5 pe-4 font-mono">404</td><td className="py-2.5">Resource not found (deliberately indistinguishable from &quot;not yours&quot;)</td></tr>
                <tr><td className="py-2.5 pe-4 font-mono">429</td><td className="py-2.5">Rate limit exceeded</td></tr>
                <tr><td className="py-2.5 pe-4 font-mono">502</td><td className="py-2.5">Upstream provisioning failure (rare from your side &mdash; provisioning happens after POST /orders already returned)</td></tr>
              </tbody>
            </table>
          </div>
        </Section>

        <Section id="getting-access" title="6. Getting API Access">
          <p>
            Key issuance and revocation are Super-Admin-only actions performed from the internal admin console
            &mdash; there is no self-service signup. If you&apos;re a merchant looking to integrate
            programmatically, contact your account admin once your partner application is approved.
          </p>
          <p>
            If you suspect your key has leaked, ask for immediate revocation &mdash; any access tokens already
            issued from it stop working on their next use, not just after they naturally expire.
          </p>
          <Link
            href="/reseller"
            className="inline-flex items-center gap-1.5 text-sm font-semibold text-brand-600 hover:text-brand-700 pt-2"
          >
            <span>Not a partner yet? Apply to the B2B Reseller Program</span>
            <ArrowRight className="w-4 h-4" />
          </Link>
        </Section>
      </div>
    </div>
  );
}
