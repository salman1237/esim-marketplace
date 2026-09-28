# Business Profile — Triptel

Version 1.0 · 28 September 2026

---

## 1. Identity

| | |
|---|---|
| **Trading name** | Triptel |
| **Website** | <https://triptel.co> |
| **Category** | Travel connectivity / prepaid eSIM data marketplace |
| **Positioning line** | *Stay connected in 200+ destinations* |
| **Home market** | Bangladesh |
| **Catalogue reach** | Global — 200+ destinations via the supplier network |
| **Launch status** | Platform live; commercial switches (payout rules, referral amounts, discount codes) awaiting configuration |
| **Registered entity, company number, registered address, directors** | **To be completed.** These are not recorded anywhere in the system. The Declaration legal page still carries bracketed placeholders and must be filled in before the page is published. |
| **Contact (operational)** | support@triptel.co · system@triptel.co (automated copies) · hello@triptel.co (outbound sender) |

> **Note for whoever completes this document:** every fact above that is not
> marked *to be completed* was read from the running system. The legal entity
> details are the only gap, and they are a gap in the system too — see
> §9 of `PROJECT_OVERVIEW.md`.

## 2. What the business sells

A **prepaid travel eSIM**: a digital SIM profile, valid in one country or
region, with a fixed data allowance and a fixed validity period. The customer
receives a QR code and an activation string by email immediately after
payment, installs it on a compatible phone, and has working mobile data the
moment they land.

A typical catalogue entry looks like *"Thailand 3 GB / 15 Days"*. The
catalogue is synchronised from the supplier every four hours, so plan
availability and cost track the supplier automatically.

Two properties of the product shape almost everything else in the business:

1. **Validity runs from first activation, not from purchase.** A traveller can
   buy a 3-day Thailand plan a fortnight before departure and it will still be
   full-length when they arrive. The platform records `activated_at` from the
   carrier, not from checkout.
2. **Delivery is instantaneous and non-physical.** There is no stock, no
   shipping, no returns logistics. The cost of a failed sale is a refund, not
   a lost unit.

## 3. The problem being solved

For a traveller from Bangladesh, staying connected abroad currently means one
of three bad options:

| Option | Problem |
|---|---|
| International roaming | Opaque per-MB pricing, bill shock on return, no cost certainty before travelling |
| Local SIM on arrival | Airport queues, passport registration, language barrier, wasted holiday time, needs a spare SIM slot |
| Existing global eSIM apps | Priced in USD, card-only checkout, no local payment method, no local support, no distribution through the travel agents customers actually use |

Triptel addresses all three at once: fixed, visible pricing before departure;
zero physical setup; and purchase in taka through bKash, Nagad or a bank
transfer — including through the travel agency that sold the ticket.

## 4. Market and customers

### Primary segments

1. **Outbound leisure and umrah/hajj travellers from Bangladesh.** Price
   sensitive, mobile-first, often paying with bKash or Nagad rather than a
   card. Frequently book through an agency rather than online.
2. **Business travellers and expatriates.** Less price sensitive, value
   reliability and a working connection on landing, buy repeatedly.
3. **Travel agencies and tour operators.** Not end customers but a
   distribution channel — they want a margin, a simple portal, and something
   they can sell at the counter while issuing a ticket.
4. **Software partners.** Online travel agencies and booking platforms that
   want to attach an eSIM to a flight booking through an API.

### Why the agency channel matters

In Bangladesh a large share of international travel is still booked in
person. An agency that already sells the ticket, the visa service and the
insurance is the natural place to sell connectivity — and it costs Triptel
nothing to acquire that customer. The merchant and agent programmes exist to
make that channel profitable for everyone in it without Triptel having to run
retail outlets.

## 5. Revenue model

Triptel earns the spread between the supplier's wholesale cost and the retail
price, minus whatever is paid out to the distribution chain.

### Pricing

Retail price is derived from supplier cost by a single, configurable markup —
the **selling profit percentage**, default **25%**. Changing it re-prices the
entire catalogue. This keeps margin predictable as supplier costs move.

```
retail price = supplier cost × (1 + selling profit %)
```

### Where the margin goes

| Recipient | Basis | Default | Notes |
|---|---|---|---|
| **Triptel** | Residual | — | Whatever is left after the below |
| **Merchant** | % of the sale price | 5%, set per merchant by admin | Can be raised per merchant; optional volume tiers override the flat rate |
| **Agent** | % of the sale price | 2% | Paid **in addition to** the merchant's commission, not out of it |
| **Agent bonus** | % of the sale price | 0%, max 10% | **Deducted from the merchant's commission** and paid to the agent. Requires admin approval. The merchant is not shown it. |

Two rules protect the model:

- The bonus is capped at the merchant's own rate, so a merchant's commission
  can reach zero but never go negative.
- If the agent is suspended, no bonus is deducted at all — the full rate goes
  back to the merchant rather than the slice vanishing.

### Secondary revenue and cost levers

- **Withdrawal fees** — flat or percentage, configurable, default zero.
- **Float** — wallet balances are held before they are spent.
- **Discounts and referral rewards** are costs, not revenue, and both are
  configurable and default to off.

## 6. Competitive position

| | Global eSIM apps | Local telco roaming | **Triptel** |
|---|---|---|---|
| Destination coverage | Wide | Wide | Wide (200+) |
| Price transparency | Good | Poor | Good |
| Local payment (bKash/Nagad) | No | N/A | **Yes** |
| Local currency pricing | Rarely | Yes | **Yes** |
| Agency distribution | No | No | **Yes — merchant + agent programmes** |
| API for partners | Some | No | **Yes** |
| Local support in-country | No | Yes | **Yes — ticketing + WhatsApp** |

The defensible position is not the eSIM itself — that is a commodity bought
from a supplier anyone could approach. It is the **distribution and payment
layer**: local rails, a working agency channel with real commission
mechanics, and an API that lets partners embed the product.

## 7. Operating model

- **No inventory.** Profiles are ordered from the supplier at the moment of
  sale.
- **Prepaid supplier balance.** Triptel holds a balance with VivaPe that
  funds each order; the admin console surfaces it so it can be topped up
  before it runs dry.
- **Small operations team.** The admin console is built so that approvals
  (KYC, merchants, deposits, withdrawals, agent bonuses) and support all run
  from one screen with queue counts on every tab.
- **Automated by default.** Catalogue sync, order recovery, webhook retries,
  notification emails and deploys all run without a human.

## 8. Key business risks

| Risk | Exposure | Current mitigation |
|---|---|---|
| Single supplier dependency | Total — no eSIM without VivaPe | Supplier calls are isolated behind one adapter module, so a second supplier is an additive change; supplier call logs and reconciliation reports exist |
| Supplier delivery failure | Customer paid, no eSIM | Order marked FAILED, automatic proportional refund, stuck-order recovery sweep every 2 minutes |
| Payment gateway failure | No card top-ups | Manual bKash/Nagad/bank deposit route is independent of the gateway |
| Promo credit leaking into cash | Direct financial loss | Reward wallet is structurally non-withdrawable; refunds split by how the order was paid |
| FX movement | Margin erosion | Base currency is EUR (the supplier's currency), so cost and price move together; withdrawal rates frozen at approval |
| Supplier's own data exposure | Third-party privacy incident | Identified: VivaPe's public status page is enumerable by sequential ID. Triptel's equivalent uses a random 128-bit token. To be raised with the supplier. |
| Regulatory / KYC | Payout compliance | KYC required before any withdrawal; documents stored outside the public file mount and served only to authenticated admins |

## 9. What success looks like

The business is working when, per month:

- eSIMs sold and net profit both grow — both are on the admin dashboard;
- a rising share of sales comes through **Partner API** and **merchant
  portal** rather than the website, since those are the channels that scale
  without marketing spend;
- failed-order rate stays near zero;
- wallet top-ups exceed wallet spend (customers are pre-loading, which is
  float and retention);
- the support queue clears faster than it fills.

Every one of these is already measured on the admin overview screen — see
`screenshots/30-admin-overview.png`.
