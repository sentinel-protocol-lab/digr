# Landing page — canonical source

This folder is the **single source of truth** for the Digr landing site served
at `sentinelprotocol.co.uk` (Cloudflare Worker `digr-landing`, static assets).

| File | Page |
|------|------|
| `index.html` | Landing page |
| `privacy-policy.html` | `/privacy-policy` |
| `terms-and-conditions.html` | `/terms-and-conditions` |

## Rules

- **Edit here, never in Cloudflare.** The live copy is a throwaway deploy
  target; the next deploy overwrites it.
- Design/layout changes are drafted in the Claude Design project, then the
  exported HTML lands **here** before deploying.
- Product facts (pricing, links, tier contents, licence wording) are edited
  directly here and verified against the real product.
- Brand casing is strict: **"Digr"**, never "DIGR".
- Pricing is locked: £29 list, £19 via the early-adopter code. The Pro button
  points at `sentinelprotocol.co.uk/digr` (a Cloudflare redirect to Gumroad
  checkout with the code pre-applied) — not the raw Gumroad URL.

## Deploy

Manual, from this folder (there is no GitHub→Cloudflare auto-deploy yet):
Cloudflare dashboard → Workers & Pages → `digr-landing` → upload these files,
or `wrangler deploy` if a wrangler config is set up. Verify after deploying:
the live page's md5 must match `md5 index.html` here.

The legal docx masters live outside the repo (Ibi's iCloud); these HTML pages
were generated from the 23/24-Jun masters with the date set at publication.
