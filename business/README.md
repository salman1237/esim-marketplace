# Triptel — Business & Technical Documentation

This folder is the written record of what Triptel is, what it does, how it is
built and how to carry the work forward. It is generated from the live
codebase and a running instance, not from memory — every endpoint count, table
name, business rule and screenshot in here was read out of the system on
**28 September 2026**.

## Where to start

| If you are… | Read |
|---|---|
| An investor, partner or new stakeholder | [`PROJECT_OVERVIEW.md`](PROJECT_OVERVIEW.md), then [`01_Business_Profile.md`](01_Business_Profile.md) |
| A product owner writing scope | [`02_Business_Requirements_Specification.md`](02_Business_Requirements_Specification.md) |
| An engineer joining the codebase | [`03_System_Architecture.md`](03_System_Architecture.md) → [`04_Software_Requirements_Specification.md`](04_Software_Requirements_Specification.md) |
| Working out who makes money and how | [`05_Business_Ecosystem.md`](05_Business_Ecosystem.md) |
| Supporting customers or training staff | [`06_System_User_Guideline.md`](06_System_User_Guideline.md) |
| Onboarding a travel agency | [`07_Merchant_Registration_Process.md`](07_Merchant_Registration_Process.md) |
| Onboarding a distributor | [`08_Agent_Registration_Process.md`](08_Agent_Registration_Process.md) |
| An AI coding agent picking this project up | [`09_AI_Agent_Continuation_Guide.md`](09_AI_Agent_Continuation_Guide.md) |
| An LLM that needs the whole picture in one file | [`10_Business_Complete_Details.md`](10_Business_Complete_Details.md) |

## Contents

```
business/
├── README.md                                    this file
├── PROJECT_OVERVIEW.md / .txt                   the entire project in one document
├── 01_Business_Profile.md                       who we are, what we sell, to whom
├── 02_Business_Requirements_Specification.md    BRS — what the business needs the system to do
├── 03_System_Architecture.md                    how the system is put together
├── 04_Software_Requirements_Specification.md    SRS — functional and non-functional requirements
├── 05_Business_Ecosystem.md                     supplier, partners, payments, money flow
├── 06_System_User_Guideline.md                  user guide, with screenshots
├── 07_Merchant_Registration_Process.md          merchant onboarding, with screenshots
├── 08_Agent_Registration_Process.md             agent onboarding, with screenshots
├── 09_AI_Agent_Continuation_Guide.md            pick the project up on another machine
├── 10_Business_Complete_Details.md              single-file brief for ChatGPT / Gemini / Claude
├── screenshots/                                 50 PNGs + INDEX.md
└── txt/                                         plain-text copies of every document above
```

## About the screenshots

All 50 images in [`screenshots/`](screenshots/) were captured from a **local
instance seeded with fictional demo data** — "Rafiqul Islam", "Wanderlust
Travels Ltd.", "SkyRoute Distribution" and so on. No real customer, merchant
or payment data appears in any image, and no production database was read to
produce them. Two visible artefacts of the local environment are expected:

- the admin dashboard shows *"Supplier balance unavailable — VivaPe login
  failed: 401"*, because the local instance is deliberately given dummy
  supplier credentials;
- links show `localhost:3010` rather than `triptel.co`.

[`screenshots/INDEX.md`](screenshots/INDEX.md) lists every file and what it
shows.

## Keeping this current

These documents describe the system as of 28 September 2026. The parts most
likely to drift are the endpoint inventory in the SRS, the data model in the
architecture document, and the screenshots. All three can be regenerated:
the endpoint list from `GET /openapi.json`, the data model from
`backend/app/models/`, and the screenshots by seeding a local instance and
re-running the capture described in
[`09_AI_Agent_Continuation_Guide.md`](09_AI_Agent_Continuation_Guide.md).
