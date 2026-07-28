# Maersk Query API Tab — UX and Mock Implementation Brief

## Objective

Add a new **Query API** tab to the existing web application alongside the current **Quote** and **Import** tabs.

The purpose of this first iteration is to demonstrate how a user could query a live Maersk Spot offer through an authorised Maersk customer integration and view the result in the same normalised format already used for parsed contract-rate sheets.

For this iteration:

- Build the complete UX.
- Use a hardcoded Maersk API-style result.
- Do **not** call a real Maersk endpoint yet.
- Clearly label the result as **Demo API response**.
- Keep all API-specific code behind an adapter so the real request contract can be inserted later without rewriting the UI.

The customer's existing contract spreadsheets continue to be handled through the current parser/import flow. The Query API tab represents **live on-demand Spot offers**, not a replacement for the contract-sheet parser.

---

## Existing navigation

The application currently has:

1. **Quote**
2. **Import**

Add:

3. **Query API**

Suggested order:

```text
Quote | Import | Query API
```

The Query API tab should visually belong to the same product and reuse the existing cards, typography, spacing, tables and quote-detail components wherever possible.

---

## Key product concept

The product combines two rate sources in one normalised UX:

```text
Contract sheets / emails
        ↓
Existing parser
        ↓
Canonical contract rates
                            \
                             → Unified quote and rate-detail UX
                            /
Approved carrier API
        ↓
Live on-demand Spot offers
```

For Maersk, the public product documentation supports an Offers-style query that returns an offer for a route, departure date and equipment, including pricing and schedule information. Exact request fields can differ by API version and by the product provisioned to the customer's integration.

Therefore:

- The frontend should use a stable internal query model.
- A future `MaerskOffersAdapter` will translate that model into the customer's exact Maersk OpenAPI contract.
- Do not couple form field names directly to one unverified external parameter name.

---

## Page structure

The Query API page should have four states:

1. **Empty search form**
2. **Loading**
3. **Results list**
4. **Expanded rate detail**

For the demo, submitting a valid search should wait approximately 600–1,000 ms and return one or more hardcoded offers.

---

## Search form

### Header

```text
Query carrier rates
Search live offers from a connected carrier account.
```

Show a small status element:

```text
Carrier connection: Maersk · Demo
```

Do not display real credential fields in this screen. Credentials will eventually be configured securely at organisation/integration level, not repeatedly entered by an operational user.

### Required fields

#### 1. Carrier

- Type: select
- Initial value: `Maersk`
- Disabled in the first iteration
- Internal value: `MAEU`

#### 2. Origin

- Type: searchable location combobox
- Required
- Accept a city, inland location, terminal or port
- Show city and country in the selected value
- Store optional location identifiers when available:
  - `unlocode`
  - `geoId`
  - `rkstCode`
  - `locationType`

Example:

```text
Alcester, GB
```

#### 3. Origin service point

- Type: segmented control or select
- Required
- Options:
  - `Door`
  - `Port / terminal`

Internal values:

```ts
"DOOR" | "PORT"
```

#### 4. Destination

- Same behaviour as Origin

Example:

```text
Bangkok, TH
```

#### 5. Destination service point

- Type: segmented control or select
- Required
- Options:
  - `Port / terminal`
  - `Door`

Internal values:

```ts
"PORT" | "DOOR"
```

Together, the origin and destination service points must support:

- Door-to-door
- Door-to-port
- Port-to-door
- Port-to-port

Do not expose carrier terminology such as CY/SD directly to ordinary users. The future adapter can map the friendly selections to the exact Maersk service-mode values.

#### 6. Departure date

- Type: date picker
- Required
- Label: `Earliest departure date`
- Must not allow a date in the past

#### 7. Equipment type

- Type: select
- Required
- Initial supported options:
  - `20' Dry Standard`
  - `40' Dry Standard`
  - `40' High Cube Dry`
  - `20' Reefer`
  - `40' High Cube Reefer`

Use a canonical internal code and retain the ISO equipment code separately.

Example mapping:

```ts
{
  canonicalCode: "40HDRY",
  isoCode: "45G1",
  label: "40' High Cube Dry"
}
```

Do not assume the example ISO code is accepted by every enabled API version. The future adapter should retrieve or validate supported equipment against the provisioned API.

#### 8. Quantity

- Type: integer stepper
- Required
- Minimum: 1
- Default: 1

#### 9. Weight per container

- Type: decimal number
- Required
- Unit selector fixed to tonnes for the first iteration
- Label: `Weight per container`
- Example: `18`

### Optional fields

Keep optional fields collapsed under:

```text
Additional cargo details
```

Include:

#### Commodity description

- Type: text
- Optional
- Do not claim it is sent to Maersk until the actual enabled API specification confirms the field.

#### Customer reference

- Type: text
- Optional
- Internal-only metadata for this application's search history.

#### Preferred currency

- Type: select
- Optional
- Options initially: `Original currencies`, `USD`, `GBP`, `EUR`
- This controls display/conversion in our application; it must not imply that the carrier API supports currency selection.

#### Show unavailable/filtered offers

- Type: checkbox
- Optional
- Default: false
- This may later map to an API option where supported.

Do not add dangerous-goods, reefer-temperature or out-of-gauge controls until we confirm the exact API product and required validation rules. They can be added in a later version.

---

## Internal query model

The form should submit this internal object:

```ts
export type CarrierRateQuery = {
  carrier: "MAERSK";
  brandScac: "MAEU";
  origin: {
    displayName: string;
    countryCode: string;
    cityName?: string;
    unlocode?: string;
    geoId?: string;
    rkstCode?: string;
    locationType?: "CITY" | "PORT" | "TERMINAL" | "INLAND";
  };
  destination: {
    displayName: string;
    countryCode: string;
    cityName?: string;
    unlocode?: string;
    geoId?: string;
    rkstCode?: string;
    locationType?: "CITY" | "PORT" | "TERMINAL" | "INLAND";
  };
  originServicePoint: "DOOR" | "PORT";
  destinationServicePoint: "DOOR" | "PORT";
  earliestDepartureDate: string; // YYYY-MM-DD
  equipment: {
    canonicalCode: string;
    isoCode?: string;
    label: string;
  };
  quantity: number;
  weightPerContainerTonnes: number;
  commodityDescription?: string;
  customerReference?: string;
  displayCurrency?: "ORIGINAL" | "USD" | "GBP" | "EUR";
  includeFilteredOffers?: boolean;
};
```

---

## API adapter boundary

Create an interface even though the result is mocked:

```ts
export interface CarrierOffersAdapter {
  searchOffers(query: CarrierRateQuery): Promise<CanonicalCarrierOffer[]>;
}
```

First implementation:

```ts
export class MockMaerskOffersAdapter implements CarrierOffersAdapter {
  async searchOffers(
    query: CarrierRateQuery,
  ): Promise<CanonicalCarrierOffer[]> {
    await new Promise((resolve) => setTimeout(resolve, 800));
    return buildMockMaerskOffers(query);
  }
}
```

Future implementation:

```ts
export class MaerskOffersAdapter implements CarrierOffersAdapter {
  // Translate our stable internal model into the exact request contract
  // downloaded from the customer's enabled Maersk Developer Portal app.
}
```

### Important implementation rule

Do not build the production request URL from guesses in this demo.

Before enabling the real integration, the client must download the OpenAPI specification for the exact Maersk Offers/pricing product enabled on its Developer Portal integration. We will then confirm:

- Production base URL
- Authentication scheme
- Exact required and optional parameters
- Accepted service-mode values
- Location identifier rules
- Equipment codes
- Weight format
- Response schemas
- Rate limits
- Storage/cache restrictions

---

## Results list

After submission, show a summary header:

```text
1 live offer found
Alcester, GB → Bangkok, TH · 1 × 40' High Cube Dry · 18 t
```

Each result card or row should show:

- Carrier: Maersk
- Product: Maersk Spot
- Route: origin → destination
- Service scope: e.g. Door-to-door
- ETD
- ETA
- Transit time
- Equipment and quantity
- Total quoted amount
- Currency
- Number of charge lines
- `Demo API response` badge
- `View details` action

Example:

```text
Maersk Spot                                      Demo API response
Alcester, GB → Bangkok, TH
Door-to-door · 1 × 40' High Cube Dry · 18 t

ETD 12 Aug 2026       ETA 5 Oct 2026       Transit 54 days

Quoted total                                      USD 2,870.97
                                                  [View details]
```

---

## Expanded rate-detail view

Reuse the visual structure of the current quote-detail screen shown in the reference image.

### Top context row

```text
Alcester, GB → Bangkok, TH
SOURCE  MAERSK OFFERS API · DEMO
```

### Summary cards

Show eight cards:

1. **Origin** — `Alcester, GB`
2. **POL** — `Felixstowe, GB`
3. **POD** — `Laem Chabang, TH`
4. **Delivery** — `Bangkok, TH`
5. **Equipment** — `40HDRY × 1`
6. **Departure** — `12 Aug 2026`
7. **Service** — `Door-to-door`
8. **Offer ID** — `O_DEMO_MAEU_50823359`

For a port-to-port result, Origin may equal POL and Delivery may equal POD.

### Charges table

Construct the same three normalised sections already used by parsed quotes:

1. **Origin charges**
2. **Freight charges**
3. **Destination charges**

Columns:

- Charge
- Basis
- Quantity
- Currency
- Unit price
- USD equivalent

The categorisation into origin/freight/destination is our canonical presentation layer. Do not imply that Maersk necessarily returns these exact three arrays. The real adapter will map carrier charge codes and locations into these sections.

### Hardcoded charge example

#### Origin charges

| Charge | Basis | Qty | CCY | Unit price | USD equiv. |
|---|---|---:|---|---:|---:|
| Inland haulage — origin | Per container | 1 | GBP | 420.00 | 535.50 |
| Origin documentation | Per document | 1 | GBP | 55.00 | 70.13 |

Origin subtotal: **USD 605.63**

#### Freight charges

| Charge | Basis | Qty | CCY | Unit price | USD equiv. |
|---|---|---:|---|---:|---:|
| Basic Ocean Freight | Per container | 1 | USD | 1,650.00 | 1,650.00 |
| Bunker adjustment | Per container | 1 | USD | 310.00 | 310.00 |
| Emissions surcharge | Per container | 1 | USD | 145.00 | 145.00 |

Freight subtotal: **USD 2,105.00**

#### Destination charges

| Charge | Basis | Qty | CCY | Unit price | USD equiv. |
|---|---|---:|---|---:|---:|
| Documentation fee — destination | Per document | 1 | THB | 1,500.00 | 45.30 |
| Container Protect Essential | Per container | 1 | THB | 850.00 | 25.67 |
| Inland haulage — destination | Per container | 1 | THB | 3,120.00 | 94.37 |

Destination subtotal: **USD 165.34**

### Total

```text
Total for 1 × 40HDRY                         USD 2,875.97
```

All hardcoded amounts are illustrative. They must never be presented as a genuine Maersk quote.

### Footer metadata

Display:

```text
Transit 54 days · Offer ID O_DEMO_MAEU_50823359
Retrieved 28 Jul 2026 at 13:45 BST · Dynamic Spot offer
```

For a live Spot result, use `Retrieved at`, not a fabricated quarterly validity period.

Optionally show:

```text
Price and space are subject to carrier confirmation at booking.
```

---

## Canonical offer model

Use a normalised result that can also support other carriers later:

```ts
export type CanonicalCarrierOffer = {
  id: string;
  carrier: {
    code: string;
    name: string;
  };
  productName: string;
  sourceType: "LIVE_API" | "MOCK_API";
  isDemo: boolean;
  offerId?: string;
  retrievedAt: string;
  rateType: "SPOT";
  rateStatus: "DYNAMIC";
  route: {
    origin: CanonicalLocation;
    portOfLoading?: CanonicalLocation;
    portOfDischarge?: CanonicalLocation;
    destination: CanonicalLocation;
    originServicePoint: "DOOR" | "PORT";
    destinationServicePoint: "DOOR" | "PORT";
  };
  equipment: {
    canonicalCode: string;
    isoCode?: string;
    label: string;
    quantity: number;
    weightPerContainerTonnes: number;
  };
  schedule: {
    departureAt: string;
    arrivalAt: string;
    transitDays: number;
    vesselName?: string;
    voyageNumber?: string;
    serviceCode?: string;
  };
  charges: CanonicalChargeLine[];
  subtotals: {
    originUsd: number;
    freightUsd: number;
    destinationUsd: number;
  };
  total: {
    amount: number;
    currency: string;
    usdEquivalent?: number;
  };
  conditions?: {
    originFreeDays?: number;
    destinationFreeDays?: number;
    notes?: string[];
  };
};

export type CanonicalLocation = {
  displayName: string;
  cityName?: string;
  countryCode: string;
  unlocode?: string;
  geoId?: string;
  locationType?: string;
};

export type CanonicalChargeLine = {
  id: string;
  section: "ORIGIN" | "FREIGHT" | "DESTINATION" | "OTHER";
  chargeCode?: string;
  chargeName: string;
  basis: "PER_CONTAINER" | "PER_SHIPMENT" | "PER_DOCUMENT" | "OTHER";
  quantity: number;
  currency: string;
  unitPrice: number;
  amount: number;
  usdEquivalent?: number;
  isOptional?: boolean;
  isZeroRated?: boolean;
};
```

---

## Hardcoded mock object

Create the demo result from the submitted query so that the selected route, equipment, quantity and weight are reflected in the result.

```ts
export const mockMaerskOffer: CanonicalCarrierOffer = {
  id: "mock-maersk-offer-1",
  carrier: {
    code: "MAEU",
    name: "Maersk",
  },
  productName: "Maersk Spot",
  sourceType: "MOCK_API",
  isDemo: true,
  offerId: "O_DEMO_MAEU_50823359",
  retrievedAt: "2026-07-28T13:45:00+01:00",
  rateType: "SPOT",
  rateStatus: "DYNAMIC",
  route: {
    origin: {
      displayName: "Alcester, GB",
      cityName: "Alcester",
      countryCode: "GB",
      locationType: "INLAND",
    },
    portOfLoading: {
      displayName: "Felixstowe, GB",
      cityName: "Felixstowe",
      countryCode: "GB",
      unlocode: "GBFXT",
      locationType: "PORT",
    },
    portOfDischarge: {
      displayName: "Laem Chabang, TH",
      cityName: "Laem Chabang",
      countryCode: "TH",
      unlocode: "THLCH",
      locationType: "PORT",
    },
    destination: {
      displayName: "Bangkok, TH",
      cityName: "Bangkok",
      countryCode: "TH",
      unlocode: "THBKK",
      locationType: "INLAND",
    },
    originServicePoint: "DOOR",
    destinationServicePoint: "DOOR",
  },
  equipment: {
    canonicalCode: "40HDRY",
    isoCode: "45G1",
    label: "40' High Cube Dry",
    quantity: 1,
    weightPerContainerTonnes: 18,
  },
  schedule: {
    departureAt: "2026-08-12T10:00:00Z",
    arrivalAt: "2026-10-05T08:00:00Z",
    transitDays: 54,
    vesselName: "Demo Vessel",
    voyageNumber: "626E",
    serviceCode: "DEMO1",
  },
  charges: [
    {
      id: "origin-haulage",
      section: "ORIGIN",
      chargeName: "Inland haulage — origin",
      basis: "PER_CONTAINER",
      quantity: 1,
      currency: "GBP",
      unitPrice: 420,
      amount: 420,
      usdEquivalent: 535.5,
    },
    {
      id: "origin-doc",
      section: "ORIGIN",
      chargeName: "Origin documentation",
      basis: "PER_DOCUMENT",
      quantity: 1,
      currency: "GBP",
      unitPrice: 55,
      amount: 55,
      usdEquivalent: 70.13,
    },
    {
      id: "basic-ocean-freight",
      section: "FREIGHT",
      chargeCode: "BAS",
      chargeName: "Basic Ocean Freight",
      basis: "PER_CONTAINER",
      quantity: 1,
      currency: "USD",
      unitPrice: 1650,
      amount: 1650,
      usdEquivalent: 1650,
    },
    {
      id: "bunker-adjustment",
      section: "FREIGHT",
      chargeName: "Bunker adjustment",
      basis: "PER_CONTAINER",
      quantity: 1,
      currency: "USD",
      unitPrice: 310,
      amount: 310,
      usdEquivalent: 310,
    },
    {
      id: "emissions-surcharge",
      section: "FREIGHT",
      chargeName: "Emissions surcharge",
      basis: "PER_CONTAINER",
      quantity: 1,
      currency: "USD",
      unitPrice: 145,
      amount: 145,
      usdEquivalent: 145,
    },
    {
      id: "destination-doc",
      section: "DESTINATION",
      chargeName: "Documentation fee — destination",
      basis: "PER_DOCUMENT",
      quantity: 1,
      currency: "THB",
      unitPrice: 1500,
      amount: 1500,
      usdEquivalent: 45.3,
    },
    {
      id: "container-protect",
      section: "DESTINATION",
      chargeName: "Container Protect Essential",
      basis: "PER_CONTAINER",
      quantity: 1,
      currency: "THB",
      unitPrice: 850,
      amount: 850,
      usdEquivalent: 25.67,
      isOptional: true,
    },
    {
      id: "destination-haulage",
      section: "DESTINATION",
      chargeName: "Inland haulage — destination",
      basis: "PER_CONTAINER",
      quantity: 1,
      currency: "THB",
      unitPrice: 3120,
      amount: 3120,
      usdEquivalent: 94.37,
    },
  ],
  subtotals: {
    originUsd: 605.63,
    freightUsd: 2105,
    destinationUsd: 165.34,
  },
  total: {
    amount: 2875.97,
    currency: "USD",
    usdEquivalent: 2875.97,
  },
  conditions: {
    originFreeDays: 5,
    destinationFreeDays: 7,
    notes: [
      "Illustrative demo only — not a bookable Maersk quotation.",
      "Final pricing and space are subject to carrier confirmation.",
    ],
  },
};
```

---

## Pricing calculations in the mock

The mock should calculate quantity-sensitive charge totals.

For example:

- `PER_CONTAINER` charge amount = unit price × container quantity
- `PER_DOCUMENT` charge amount = unit price × 1
- Section subtotal = sum of USD equivalents in that section
- Overall total = sum of all section subtotals

This allows the UX to behave realistically when the user changes quantity, even though the rates themselves are hardcoded.

Keep FX rates in one mock configuration object rather than scattering conversion constants through components.

---

## Empty, loading and error states

### Loading

Show:

```text
Searching Maersk offers…
Checking routes, schedules and available pricing.
```

Use a skeleton for result cards.

### No offers

```text
No offers found for this search.
Try another departure date, service scope or equipment type.
```

Include an action to edit the search.

### Demo error toggle

Optionally add a development-only switch or query parameter to simulate:

- Invalid location
- Unsupported equipment
- No route available
- Carrier API unavailable
- Authorisation missing

Do not expose this toggle in production UI.

---

## Visual accuracy and labelling

The page must never imply that hardcoded amounts are genuinely returned by Maersk.

Required labels:

- `Demo API response`
- `Illustrative pricing`
- `Not bookable`

The normalised table can look production-ready, but source transparency must remain visible.

Use:

```text
SOURCE  MAERSK OFFERS API · DEMO
```

Do not use:

```text
SOURCE  MAERSK API
```

without the demo qualifier.

---

## What is confirmed versus pending

### Safe to represent in the UX

- A customer can create an integration in the Maersk Developer Portal and request API products using its customer code.
- API access is scoped to the products and customer resources approved for the integration.
- Maersk uses a Consumer Key and, for protected products, OAuth client credentials.
- An Offers-style query is based on route, date and equipment/cargo inputs.
- Offers can contain schedule information, pricing, charge breakdowns and demurrage/detention conditions.
- The application can normalise returned carrier charge lines into origin, freight and destination sections.
- A friendly door/port UX can support door-to-door, door-to-port, port-to-door and port-to-port searches.

### Must remain an implementation assumption until the client's API spec is available

- Exact Offers API product name exposed in the customer's portal
- Whether that customer is already entitled to the pricing product
- Exact endpoint and hostname
- Exact parameter names
- Whether locations are sent as city/country, UN/LOCODE, GeoId, RKST code or a combination
- Whether service scope is represented as separate origin/destination service modes or a combined haulage parameter
- Exact equipment and container-weight format
- Whether the response contains negotiated contract rates, Spot offers only or another entitled product
- Exact charge-code taxonomy
- Data retention and caching constraints

---

## Real-integration checklist

When the client is ready to connect its Maersk account:

1. Client logs into the Maersk Developer Portal.
2. Client creates or opens its customer integration.
3. Client confirms the customer code(s) provisioned to the integration.
4. Client confirms which API products are enabled.
5. Client requests the Offers/pricing product if it is not enabled.
6. Client downloads the OpenAPI specification from the enabled API-product page.
7. Client creates a dedicated Consumer Key for this internal tool where practical.
8. Credentials are stored only in the backend secret manager.
9. Implement OAuth token handling if required by the product.
10. Replace `MockMaerskOffersAdapter` with `MaerskOffersAdapter`.
11. Add contract tests using Maersk's sandbox/test responses.
12. Compare API results against the same search in the client's Maersk portal.
13. Confirm whether displayed prices are Spot, contract-entitled or otherwise customer-specific.

---

## Acceptance criteria for this demo iteration

- [ ] Query API tab appears beside Quote and Import.
- [ ] User can select origin and destination.
- [ ] User can choose Door or Port independently at each end.
- [ ] User can choose departure date, equipment, quantity and weight.
- [ ] Form has clear validation.
- [ ] Submitting shows a realistic loading state.
- [ ] A hardcoded Maersk Spot result is returned.
- [ ] Result summary shows route, ETD, ETA, transit and total.
- [ ] Expanded detail reuses the existing quote-detail design.
- [ ] Charges are grouped into origin, freight and destination.
- [ ] Quantity-sensitive mock calculations work.
- [ ] Result is visibly marked Demo API response / Illustrative pricing / Not bookable.
- [ ] API logic is behind a `CarrierOffersAdapter` interface.
- [ ] No real Maersk credentials or endpoint calls are added.
- [ ] Existing Quote and Import flows continue to work unchanged.

---

## Reference material

Use the exact OpenAPI document downloaded from the client's Maersk Developer Portal as the source of truth before implementing the live adapter.

Public reference points:

- Maersk Developer Portal — Getting Started and FAQs: `https://developer.maersk.com/support/faqs`
- Maersk Developer API Catalogue: `https://developer.maersk.com/api-catalogue`
- Maersk Product Offers documentation, where available: `https://api-spt.env.productmanagement.maersk.com/offers/docs/`

A public derivative collection currently describes an Offers query with route, departure date, equipment and service-mode inputs and a response containing total price, price breakdown, schedule and D&D information. Treat this only as implementation guidance, not as a substitute for the customer's enabled OpenAPI specification.
