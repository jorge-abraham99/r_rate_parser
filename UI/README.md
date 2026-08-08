# Reudan Rate Desk v5 frontend

The authenticated frontend has three screens:

1. **Login** (`/ui/login.html`) — invite-only Supabase email/password login.
2. **Import** (`/ui/import.html`) — source tracking, upload review, publish, supersede/archive, and parse summaries.
3. **Quote** (`/ui/`) — contract-rate filtering, ranked routing comparisons, inland-haulage/POA presentation, and charge breakdowns.

The v5 UI is a vanilla HTML/CSS/JavaScript application served by the existing FastAPI static-file mount. It does not require a build step.

The source roster is provider-led and supports multiple services per provider. Quote results compare Maersk, MSC, and Hapag-Lloyd contract rates, with UK Inland Haulage attached as a separate service where appropriate. The shared routing vocabulary is quay-to-quay and door-to-quay.

## Authentication

`auth.js` loads browser-safe values from `/api/public-config`, restores the Supabase session, and adds its access token to every rate API call. A `401` clears the local session and returns the user to login. A `403` shows that the signed-in user does not have the required membership or role.

The browser library is pinned to `@supabase/supabase-js` `2.112.2` and protected by a SHA-384 integrity value. The login page has no sign-up action. `app.js` and `rate-desk.js` must use `RATE_DESK_AUTH.apiFetch`; do not add direct `fetch` calls for rate APIs.

## Demo mode

`config.js` contains the temporary frontend switch:

```js
window.RATE_DESK_CONFIG = Object.freeze({
  demoMode: true,
});
```

With demo mode enabled:

- both screens show a visible **Demo data** label;
- the fixtures in `demo-data.js` drive the complete v5 experience;
- uploads, publishing, archiving, deletion, and menus are browser-session simulations;
- no file is uploaded and no backend data is changed;
- refreshing the page resets the demo.

Set `demoMode` to `false` when the backend work is ready. The screens then use the existing `/api/imports`, `/api/imports/{id}`, approval/deletion, and `/api/rate-desk` endpoints.

## Connected-mode adapter boundary

The frontend normalizes existing endpoint responses into provider/service rows, parse summaries, routing rows, service tags, and charge buckets. It does not change the endpoint contracts.

Until the backend supplies the v5 source registry, inland-haulage lookup, routing variants, and POA fields, connected mode:

- derives the six known provider/service rows from current import metadata;
- hides the collection selector when no haulage choices are returned;
- labels current contract rates as `Quay to quay` or `Door to quay`;
- keeps door-to-quay rates separate from quay-to-quay rates with UK Inland Haulage;
- renders unavailable inland values as `—`;
- filters Spot-labelled imports and rates out of the v5 experience.

The historical Query API specification remains elsewhere in the repository, but its demo frontend page is no longer part of v5.

## Source files

- `index.html`, `rate-desk.js` — Quote
- `import.html`, `app.js` — Import
- `styles.css` — shared v5 design system
- `login.html`, `login.js` — invite-only login
- `auth.js` — session handling and shared authenticated API calls
- `config.js` — demo/connected mode switch
- `demo-data.js` — isolated handoff fixtures
