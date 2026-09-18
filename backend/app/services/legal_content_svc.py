"""Terms, privacy, data and refund policies - editable by the Super Admin.

Each document is one private PlatformSetting ("legal_<slug>") served by its
own endpoint rather than /settings/public, which every page load fetches and
shouldn't carry pages of policy text. Until a Super Admin saves a version,
the built-in draft below is served; the drafts are a starting point for the
business to review, not legal advice.

Bodies use a tiny markdown subset (# / ## headings, "- " bullets, **bold**,
blank-line paragraphs) that the frontend renders as plain React elements -
never as raw HTML. {platform_name} and {support_email} are filled in from
branding when served publicly, so a rename doesn't need every policy edited."""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import PlatformSetting

MAX_LEGAL_BODY_CHARS = 60_000

# Order is the order shown in the footer and the admin editor. Slugs are
# the URLs (/legal/<slug>) and the storage keys, so keep them stable -
# "data-policy" is titled Data Privacy but keeps its original URL.
LEGAL_TITLES = {
    "privacy": "Privacy Policy",
    "data-policy": "Data Privacy",
    "terms": "Terms & Conditions",
    "declaration": "Declaration",
    "refund-policy": "Refund Policy",
    "payment-policy": "Payment Policy",
}

DEFAULT_LEGAL_BODIES = {
    "terms": """These Terms & Conditions govern your use of {platform_name} (the "Service"), including our website, customer wallet, merchant portal and Partner API. By creating an account, signing in with Google, or buying an eSIM you agree to them.

## 1. The Service
{platform_name} sells prepaid travel eSIM data plans supplied by our network partners. An eSIM is a digital SIM profile that you install on a compatible device by scanning a QR code or using an install link.

## 2. Your account
- You must give accurate details and keep your password private. You are responsible for all activity on your account.
- You must be at least 18 years old, or use the Service with the permission of a parent or guardian.
- We may ask you to verify your identity (KYC) before enabling some features such as merchant accounts or large deposits.
- We may suspend accounts involved in fraud, chargebacks, abuse or breach of these Terms.

## 3. Device compatibility
It is your responsibility to check that your device supports eSIM and is not carrier-locked **before** you buy. An eSIM that cannot be installed because of an incompatible or locked device is not a fault of the Service.

## 4. Plans, activation and validity
- Each plan shows its data allowance, validity period and coverage country or region at the time of purchase.
- Validity normally starts when the eSIM first connects to a supported network in the destination, unless the plan says otherwise.
- Unused data expires at the end of the validity period and is not carried over or refunded.
- Network speed and coverage depend on the local partner network and may vary.

## 5. Prices and payment
- Prices are shown in Euro (EUR). Amounts shown in other currencies are estimates for convenience; the EUR price is the price charged.
- You can pay from your {platform_name} wallet. The wallet can be topped up through our payment gateway or by manual deposit to one of the accounts listed on the wallet page; manual deposits are credited after we verify the transaction.
- Wallet balance is not a bank account, earns no interest, and can only be used on the Service except where the Refund Policy says otherwise.

## 6. Merchants and API partners
Approved merchants and API partners buy eSIMs for their own customers using their wallet balance. They are responsible for their customers, for keeping API keys secret, and for all orders placed with their keys. Commission is earned only on completed orders and may be reversed if an order is refunded.

## 7. Acceptable use
You must not resell the Service without an approved merchant account, use it for unlawful purposes, attempt to access other users' data, interfere with the platform, or use stolen payment methods.

## 8. Refunds
Refunds are handled under our Refund Policy, which forms part of these Terms.

## 9. Liability
The Service is provided "as is". To the extent permitted by law, {platform_name} is not liable for indirect or consequential losses, including missed connections, lost business or charges from other carriers. Our total liability for any order is limited to the amount you paid for that order.

## 10. Changes
We may update these Terms. The date of the latest version is shown on this page; continuing to use the Service after a change means you accept the updated Terms.

## 11. Governing law
These Terms are governed by the laws of Bangladesh, and disputes are subject to the courts of Dhaka.

## 12. Contact
Questions about these Terms: {support_email}
""",
    "privacy": """This Privacy Policy explains what personal information {platform_name} collects, why, and the choices you have.

## Information we collect
- **Account details:** name, username, email address, phone number and password (stored only as a secure hash).
- **Google sign-in:** if you sign in with Google we receive your name, email address, profile photo and a Google account identifier. We never receive your Google password.
- **Identity verification (KYC):** national ID number and document images, when you submit them.
- **Orders and eSIMs:** the plans you buy, eSIM identifiers (ICCID), activation codes and order history.
- **Payments:** wallet transactions, deposit transaction IDs and payment gateway references. We do not store card numbers.
- **Technical data:** IP address, browser type and security logs used to protect accounts and investigate fraud.

## How we use it
- To create and secure your account and let you sign in.
- To deliver and support your eSIM, including sending it by email.
- To process wallet top-ups, purchases, refunds and merchant commission.
- To prevent fraud, meet legal and accounting obligations, and resolve disputes.
- To send service messages. We only send marketing if you have agreed to it.

## Who we share it with
We share only what each party needs to provide the Service:
- **eSIM network suppliers**, to issue and manage your eSIM.
- **Payment gateways**, to process top-ups.
- **Email and hosting providers**, to operate the platform.
- **Merchants**, only for orders placed through that merchant.
- **Authorities**, when required by law.

We do not sell your personal information.

## Retention
We keep account and order records for as long as your account is active and afterwards for as long as needed for legal, tax and dispute purposes. See our Data Privacy page for details.

## Your rights
You can view and update your profile at any time, and ask us for a copy of your data, to correct it, or to delete your account, subject to records we must keep by law. Contact {support_email}.

## Cookies and local storage
We use browser storage to keep you signed in and remember preferences such as language and currency. We do not use third-party advertising cookies.

## Changes
We will post any update to this policy on this page with its new date.

## Contact
{support_email}
""",
    "data-policy": """This Data Privacy notice describes how {platform_name} stores, protects and retains your data. It supplements our Privacy Policy.

## Where data is stored
Platform data is stored on secured servers operated by our hosting provider. Access is limited to authorised staff who need it for their role.

## Security measures
- All traffic to the platform is encrypted with HTTPS.
- Passwords are stored only as salted hashes; API keys are stored hashed and shown to merchants once.
- Identity documents are stored separately from public files and are visible only to authorised administrators.
- Administrative actions such as wallet adjustments, price changes and approvals are recorded in an audit log.
- Wallet balances are kept in a double-entry ledger so every credit and debit can be traced.

## Retention periods
- **Account profile:** while the account is active, and up to 12 months after closure.
- **Orders, wallet ledger and payment records:** at least 6 years, for accounting and tax purposes.
- **Identity (KYC) documents:** while the account is active and up to 5 years after closure, or as required by law.
- **Security and audit logs:** up to 24 months.
- **Supplier request logs:** up to 12 months.

## Deleting your data
You can ask us to delete your account by writing to {support_email}. We will delete or anonymise personal data that we are not legally required to keep and tell you what must be retained and why.

## Data breaches
If a breach affects your personal data we will notify you and the relevant authorities without undue delay, as required by law.

## Contact
{support_email}
""",
    "refund-policy": """eSIMs are digital products that are delivered instantly, so refunds depend on whether the eSIM has been installed or used.

## Automatic refunds
If an order fails and no eSIM is issued, the full amount is returned to your {platform_name} wallet automatically. You do not need to contact us.

## Eligible for a refund
You can request a refund within **7 days** of purchase when:
- the eSIM has **not** been installed on any device, or
- the eSIM cannot connect in the covered destination because of a fault on our or our supplier's side, and our support team cannot fix it.

## Not eligible for a refund
- The eSIM has been installed or has used any data, except for a network fault described above.
- Your device is not eSIM compatible or is carrier-locked.
- You bought the wrong destination or plan.
- The validity period has ended, or data was left unused.
- The eSIM was deleted from your device. (Deleted eSIMs usually cannot be reinstalled.)

## How refunds are paid
Approved refunds are credited to your {platform_name} wallet, normally within 3 working days. If you would prefer a refund to your original payment method, tell us when you ask; that can take up to 14 working days and gateway fees may be deducted.

## Wallet balance
Wallet balance is meant to be spent on the Service. If you close your account, unused balance from a verified top-up can be returned on request, less any payment processing fees. Promotional credit cannot be withdrawn.

## Merchant and API orders
Customers who bought through a merchant should contact that merchant. Merchants request refunds from us on their customers' behalf, and any commission earned on a refunded order is reversed.

## How to ask
Email {support_email} with your order number, the email on your account and a short description of the problem (screenshots help).
""",
    "declaration": """{platform_name} makes the following declaration to its customers, partners and the relevant authorities.

## Who we are
- **Business name:** [Registered business name]
- **Trade licence:** [Trade licence number and issuing authority]
- **TIN / BIN:** [TIN] / [BIN]
- **Registered address:** [Full business address]
- **Contact:** {support_email}

## What we sell
{platform_name} sells prepaid travel eSIM data plans for use abroad, delivered digitally as a QR code or install link. We do not sell physical SIM cards and do not provide mobile service inside Bangladesh.

## Our commitments
- The full price is shown before you pay, with no hidden charges.
- Each plan's data allowance, validity and coverage are shown before purchase, and that is what you receive.
- Payments are handled by a licensed payment service provider. We never see or store your card number or mobile-banking PIN.
- If an eSIM cannot be delivered, the full amount is refunded as described in our Refund Policy.
- We aim to acknowledge every complaint within 24 hours and resolve it within 7 working days.
- We operate in line with the laws of Bangladesh that apply to digital commerce, consumer protection and data protection.

## Your declaration as a customer
By buying an eSIM you confirm that:
- your device supports eSIM and is not carrier-locked;
- you will use the plan lawfully while travelling;
- the details you give us are accurate.

## Merchants and partners
Approved merchants and API partners declare that they sell our eSIMs only to genuine customers, pass on accurate plan information, and keep to this declaration.

## Updates
We review this declaration regularly. The date of the latest version is shown at the top of this page.
""",
    "payment-policy": """This Payment Policy explains how you can pay {platform_name}, in which currency, and what happens if a payment fails.

## Ways to pay
- **Card and mobile banking** through ShurjoPay, a payment gateway licensed in Bangladesh: bKash, Nagad, Rocket, Visa, Mastercard and other methods it supports.
- **{platform_name} wallet** — pay instantly from a balance you have topped up.
- **Manual deposit** to an account listed on the wallet page, where available. It is credited after we verify your transaction ID.

## How Buy Now works
- If your wallet balance covers the plan, you choose whether to pay from your wallet or by card / mobile banking.
- If it doesn't, you go straight to the secure ShurjoPay checkout.

Your eSIM is issued only after the payment is confirmed.

## Currency
Prices are set in Euro (EUR). When you pay in Taka (BDT), the amount is converted at the rate shown at checkout, and that is the amount charged. Your bank or mobile-wallet provider may charge its own fees.

## Security
Card and mobile-banking details are entered on ShurjoPay's secure page. {platform_name} never receives or stores your card number, CVV or PIN.

## Failed or interrupted payments
- If a payment fails or you cancel it, you are not charged.
- If you are charged but the eSIM cannot be issued, the full amount is returned to your wallet automatically.
- If money leaves your account but no order appears within 30 minutes, email {support_email} with the transaction ID.

## Minimum amounts
The payment gateway does not accept payments below 10 BDT. Wallet top-ups have minimum and maximum amounts, shown on the wallet page.

## Wallet balance
Wallet balance is prepaid credit for purchases on {platform_name}. It is not a bank account and earns no interest. See our Refund Policy for when a balance can be returned.

## Merchants
Merchants pay for their customers' eSIMs the same way — from their wallet, or by ShurjoPay when the balance is short. Commission is credited to the merchant's commission wallet when the eSIM is delivered.

## Questions
{support_email}
""",
}


def setting_key(slug: str) -> str:
    return f"legal_{slug}"


async def get_legal_document(db: AsyncSession, slug: str) -> Optional[dict]:
    """Saved version if there is one, else the built-in draft. None for an unknown slug."""
    if slug not in LEGAL_TITLES:
        return None
    res = await db.execute(select(PlatformSetting).where(PlatformSetting.key == setting_key(slug)))
    setting = res.scalar_one_or_none()
    value = setting.value if setting and isinstance(setting.value, dict) else None
    if value and (value.get("body") or "").strip():
        return {"slug": slug, "title": LEGAL_TITLES[slug], "body": value["body"], "updated_at": value.get("updated_at"), "is_default": False}
    return {"slug": slug, "title": LEGAL_TITLES[slug], "body": DEFAULT_LEGAL_BODIES[slug], "updated_at": None, "is_default": True}


async def save_legal_document(db: AsyncSession, slug: str, body: str, admin_id: str):
    """Empty body resets to the built-in draft. Returns (before_body, after_doc). Caller commits."""
    before = await get_legal_document(db, slug)
    body = body.replace("\r\n", "\n").strip()
    value = {"body": body, "updated_at": datetime.now(timezone.utc).isoformat()} if body else {}

    res = await db.execute(select(PlatformSetting).where(PlatformSetting.key == setting_key(slug)))
    setting = res.scalar_one_or_none()
    if setting:
        setting.value = value
        setting.updated_by_id = admin_id
    else:
        db.add(PlatformSetting(key=setting_key(slug), value=value, is_public=False, updated_by_id=admin_id))
    await db.flush()
    return before["body"], await get_legal_document(db, slug)


def fill_placeholders(body: str, platform_name: Optional[str], support_email: Optional[str]) -> str:
    return (body
            .replace("{platform_name}", platform_name or "our platform")
            .replace("{support_email}", support_email or "our support team"))
