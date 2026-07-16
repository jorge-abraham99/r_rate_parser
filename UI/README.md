# Handoff: Reudan Rate Desk — Rate Lookup (Flow 1: RFQ → best rate)

## Overview
Internal tool for Reudan International's freight operators. Flow 1 only: an operator receives an RFQ, selects origin port (POL) and destination port (POD), and instantly sees a ranked table of all doable carrier rates parsed from the rate sheets the team receives (MSC, COSCO, Maersk Excel files + a UK waste-haulage sheet), with the cheapest rate recommended. Goal: quote customers faster than competitors.

Out of scope for this version (deliberately removed during review): rate-sheet ingestion UI, margin/sell price, copy-quote message, request-spot-rate actions.

## About the Design Files
`Rate Lookup v1.dc.html` is a **design reference created in HTML** — a working prototype showing intended look and behavior, not production code.

The repo now also contains a real connected UI at `UI/index.html` backed by `rate_ingest/api.py`. The design prototype still matters as a visual reference, but the connected page is the actual operator entrypoint for the current parser workflow.

The `rates/` xlsx files are the real carrier sheets the parser will ingest — included so the data model can be validated against reality.

## Fidelity
**High-fidelity** for layout, hierarchy, and branding; **sample data** hard-coded in the prototype (parsed by hand from the four xlsx files, with validity dates shifted to July 2026 for demo purposes). The real app should drive the same UI from the parser's output table.

## Screen: Rate Lookup
Single screen, full viewport, vertical stack:

1. **Top bar** — dark navy `#0f3466`, 10px 20px padding. Left: 26px logo square (`#2079d8`, radius 6, white "R"), "REUDAN" 600 + "Rate Desk" muted `#8fa9c9`. Right: "Rates refreshed today 07:40" 11.5px `#8fa9c9`.
2. **Search row** — bg `#f3f7fc`, border-bottom `#c9d6e6`, 16px 20px padding, flex with 12px gap, labels above controls (10px, 700, uppercase, letter-spacing .08em, `#5f7189`):
   - Origin port (POL): select — Felixstowe / Liverpool / Southampton
   - "→" separator
   - Destination port (POD): select — union of PODs found in sheets (Jakarta / Surabaya / Semarang, Port Klang / Penang, Ho Chi Minh, Haiphong, Vung Tau / Da Nang, Laem Chabang, Manila, Mundra, Nhava Sheva (JNPT), Tuticorin)
   - Container size: select — 20′ / 40′ / 40′ HC (only 40′ HC has data today)
   - Door pickup (optional): select of UK cities from the haulage sheet with £/ctn price (e.g. Aberdare · £369)
   - Primary selects: 38px height, 1.5px border `#16273b`, radius 5, white bg, 14px 600. Secondary (door): border `#b6c5d8`.
   - No submit button — results recompute live on any change.
3. **Results header line** — "Felixstowe → Jakarta / Surabaya / Semarang" 15px 700 + "4 parsed rates · best $284 MSC" 12.5px `#5f7189`. If door pickup set, amber chip: "Door: Aberdare → +£369/ctn to port (waste haulage Q3 sheet)" (bg `#fdf6e3`, border `#e3d3a1`, text `#7a5c10`).
4. **Results table** — white card, border `#c3d1e2`, radius 7, `overflow-x:auto`, rows min-width 1110px. Grid columns: `30px minmax(150px,1.3fr) minmax(115px,1fr) 62px 62px 62px 62px 62px 95px 115px`, 10px column-gap, 11px 14px row padding.
   - Header row: 9.5px 700 uppercase `#5f7189`, 1.5px bottom border `#16273b`. Columns: # · Carrier · Source · Base · Haulage · THC · Docs · Surch. · All-in $/40′ · Validity. Numeric columns right-aligned.
   - Rows sorted by all-in ascending; row 1 = recommended: bg `#e9f1fc`, 3px inset left border `#1b4f9c`, navy "BEST RATE" badge (9.5px 700 uppercase, radius 3) after carrier name.
   - Carrier 14px 700. Source cell: small mono chip (PEUTE / PAPER / QT) + truncated sheet filename 10.5px mono `#8798ac`.
   - Numbers in IBM Plex Mono; component costs 12.5px `#33475e`, All-in 15px 700. "—" where the sheet doesn't break the cost out.
   - Validity chip: green (`#e3f2e7` / `#177a46` / border `#b5dcc2`) e.g. "to 31 Jul"; amber (`#fdf0d8` / `#8a5d07` / border `#e8d3a2`) e.g. "expires 20 Jul" when within ~7 days.
   - Click row → expandable detail panel (bg `#eef4fb`, dashed top border): "BREAKDOWN · USD PER 40′HC (FROM SHEET)" + every line item from the sheet in mono, then fineprint (subject-to clauses, free time, per-B/L fees, caveats like "Quote issued ex-Rotterdam; UK loading to be confirmed").
   - Coverage-gap strip under rows (bg `#eef4fb`, 11.5px `#5f7189`): "No rate on this lane from Maersk in the parsed sheets."
   - Empty state (no rates for lane/size): centered 13px `#5f7189` "No parsed rates for this lane and container size."
5. **Footnotes** — 11px `#8798ac`: "Figures = USD per 40′HC, all-in port-to-port as parsed from carrier sheets." · "Click a row for the surcharge breakdown."

## Interactions & Behavior
- All four selects recompute results instantly (filter + sort, no loading state needed at this scale).
- Row click toggles its breakdown panel (one open at a time; changing lane closes it).
- Door pickup only adds the informational GBP haulage line — it does NOT change USD figures or ranking (known simplification; real version should use the haulage column matching the chosen POL and could rank by door total).
- Container sizes other than 40′ HC currently yield the empty state (sheets contain 40′ only).

## State Management
`origin, dest, size, door, expandedRowId` — plus the parsed-rates table as input data.

Rate record shape (what the parser should emit per lane/carrier/sheet):
```
{ carrier, sourceSheet, contractTag (e.g. PEUTE/PAPER/quote-id), kind (contract|spot),
  origins[], dest, containerSize, allInUsd,
  components: { base, haulage, thc, docs, surcharges } (nullable per field),
  breakdownLineItems[], validFrom, validTo, freetime, finePrint }
```
Business rules shown in the design: "best" = lowest all-in among valid rates; validity within 7 days → amber; missing carriers on a lane are stated explicitly; docs charged per B/L (MSC £30/BL) stay in fineprint, per-container docs (Maersk EUR 30 ≈ $35) get the Docs column; MSC's negative base ocean freight from the sheet is displayed as positive (client preference).

## Design Tokens
- Brand navy `#0f3466` (top bar) · accent blue `#1b4f9c` (best-rate, links) · logo blue `#2079d8`
- Page bg `#d7e2ef` · panel bg `#f3f7fc` · card white · expanded bg `#eef4fb`
- Borders `#c9d6e6` / `#c3d1e2` / row `#e4ebf4` · strong border/text `#16273b`
- Text: body `#33475e` · labels `#5f7189` · muted `#8798ac`
- Status green `#177a46`/`#e3f2e7`, amber `#8a5d07`/`#fdf0d8`, door-chip amber `#7a5c10`/`#fdf6e3`
- Type: Poppins (400–700) for UI; IBM Plex Mono for all numerics/filenames. Sizes as listed above; radius 5–7px; shadow `0 1px 3px rgba(20,30,25,.07)`.

## Assets
No images/icons. Fonts from Google Fonts (Poppins, IBM Plex Mono). Reudan logo approximated as a blue rounded square + "R" — replace with the real mark.

## Files
- `Rate Lookup v1.dc.html` — the prototype (markup + logic + sample data in one file)
- `rates/msc.xlsx`, `rates/cosco.xlsx`, `rates/maersk.xlsx`, `rates/haulage.xlsx` — the real source sheets the sample data was parsed from
