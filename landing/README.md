# Landing page — canonical source

This folder is the **single source of truth** for the Digr landing site served
at `sentinelprotocol.co.uk` (Cloudflare Worker `digr-landing`, static assets).

| File | Serves |
|------|--------|
| `digr/index.html` | `/digr` — the Digr landing page |
| `_redirects` | Cloudflare redirect rules: `/` → `/digr`, and `/digr/pro` → Gumroad |
| `privacy-policy.html` | `/privacy-policy` |
| `terms-and-conditions.html` | `/terms-and-conditions` |
| `og-card.png` | `/og-card.png` — link-preview image (not a page) |

## Rules

- **Edit here, never in Cloudflare.** The live copy is a throwaway deploy
  target; the next deploy overwrites it.
- Design/layout changes are drafted in the Claude Design project, then the
  exported HTML lands **here** before deploying.
- Product facts (pricing, links, tier contents, licence wording) are edited
  directly here and verified against the real product.
- Brand casing is strict: **"Digr"**, never "DIGR".
- Pricing (£29 list, £19 early adopter, and a free launch window) is driven by
  Gumroad's own **scheduled windows**, NOT by a code in the link. The Pro button
  points at `/digr/pro`, a Cloudflare redirect (see `_redirects`) to the plain
  Gumroad product URL `sentinelprotocol.gumroad.com/l/digr`. No discount code is
  baked into the link, so the one link serves every launch phase — free → £19 →
  £29 — without a redeploy.

## Deploy

Manual, from this folder (there is no GitHub→Cloudflare auto-deploy yet):
Cloudflare dashboard → Workers & Pages → `digr-landing` → upload the contents of
this folder **keeping the folder structure** (so `digr/index.html` stays inside a
`digr/` folder, and `_redirects`, `og-card.png` and the two legal pages sit at the
top level), or `wrangler deploy` if a wrangler config is set up. The custom domain
`sentinelprotocol.co.uk` is attached under the Worker's Settings → Domains &
Routes — that attachment is what creates the DNS record.

Verify after deploying — the site cannot detect its own broken outbound links, so
check with `curl`, not by eye:
- `curl -sI https://sentinelprotocol.co.uk/digr` → `200`
- `curl -sI https://sentinelprotocol.co.uk/` → `302`, `Location: /digr`
- `curl -sI https://sentinelprotocol.co.uk/digr/pro` → `302` toward Gumroad
- `curl -sI https://sentinelprotocol.co.uk/og-card.png` → `200`

**Upload `og-card.png` too, not just the HTML.** `index.html` points its
`og:image` / `twitter:image` tags at the absolute URL
`https://sentinelprotocol.co.uk/og-card.png`. If the PNG is missing from the
deploy, every shared link renders with a broken or blank preview card, and the
failure is invisible from the page itself. After deploying, confirm
`curl -sI https://sentinelprotocol.co.uk/og-card.png` returns `200`.

The legal docx masters live outside the repo (Ibi's iCloud); these HTML pages
were generated from the 23/24-Jun masters with the date set at publication.
