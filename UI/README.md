# Reudan Rate Desk v4 frontend

The operator frontend has two screens:

1. **Import** (`/ui/import.html`) — source tracking, upload review, publish, supersede/archive, and parse summaries.
2. **Quote** (`/ui/`) — contract-rate filtering, ranked routing comparisons, inland-haulage/POA presentation, and charge breakdowns.

The v4 UI is a vanilla HTML/CSS/JavaScript application served by the existing FastAPI static-file mount. It does not require a build step.

## Demo mode

`config.js` contains the temporary frontend switch:

```js
window.RATE_DESK_CONFIG = Object.freeze({
  demoMode: true,
});
```

With demo mode enabled:

- both screens show a visible **Demo data** label;
- the fixtures in `demo-data.js` drive the complete v4 experience;
- uploads, publishing, archiving, deletion, and menus are browser-session simulations;
- no file is uploaded and no backend data is changed;
- refreshing the page resets the demo.

Set `demoMode` to `false` when the backend work is ready. The screens then use the existing `/api/imports`, `/api/imports/{id}`, approval/deletion, and `/api/rate-desk` endpoints.

## Connected-mode adapter boundary

The frontend normalizes existing endpoint responses into source rows, parse summaries, routing rows, source tags, and charge buckets. It does not change the endpoint contracts.

Until the backend supplies the v4 source registry, inland-haulage lookup, routing variants, and POA fields, connected mode:

- derives the three known source rows from current import metadata;
- hides the collection selector when no haulage choices are returned;
- shows current contract rates as `CY/CY`;
- renders unavailable inland values as `—`;
- filters Spot-labelled imports and rates out of the v4 experience.

The historical Query API specification remains elsewhere in the repository, but its demo frontend page is no longer part of v4.

## Source files

- `index.html`, `rate-desk.js` — Quote
- `import.html`, `app.js` — Import
- `styles.css` — shared v4 design system
- `config.js` — demo/connected mode switch
- `demo-data.js` — isolated handoff fixtures
