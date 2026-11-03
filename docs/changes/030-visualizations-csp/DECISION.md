# 030 — A Content-Security-Policy for the visualization pages
**Date:** 2026-10
**MR:** https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/merge_requests/198
---
## Context

The pages in `visualizations/` are single HTML files with inline scripts and styles and fonts embedded as `data:`
URIs; by design they load nothing from the network. So far only the smoke tests check this, and only in Chromium on
the test machine. A reviewer suggested that the pages declare a Content-Security-Policy (CSP): a rule set that the
reader's browser itself enforces, so that it blocks a load from the network even if a later edit adds one by
mistake. The pages have no web server that could send the policy as an HTTP header; readers open them from a file or
through htmlpreview.github.io, which the README links. A policy can also be given in the page, as
`<meta http-equiv="Content-Security-Policy">`.

What the pages use: inline `<script>` and `<style>` elements; `style="…"` attributes (elasticity page); inline SVG
whose markers and clip paths refer to elements of the same page (`url(#…)`); a WebGL canvas with three.js
(row-or-column page); two fonts as `data:` URIs (row-or-column page). They use no images, workers, `blob:` URLs,
`eval`, inline event handlers (`onclick="…"`), forms or frames.

## Decision

Every page carries, right after `<meta charset="utf-8">`, the same line:

```html
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; font-src data:">
```

- `default-src 'none'` forbids every kind of load that has no rule of its own: requests from scripts (`fetch`,
  `XMLHttpRequest`, WebSocket), images, media and frames.
- `script-src 'unsafe-inline'` allows scripts written into a page and nothing else: external scripts and workers are
  blocked by this rule, and `eval` and `new Function` (code built from text while the page runs) stay forbidden.
  Without it no page runs. It would also allow a script that someone injects into a page; the pages take no input
  from outside that could do so (see Alternatives rejected).
- `style-src 'unsafe-inline'` allows the `<style>` elements and `style="…"` attributes of the page, and blocks
  external stylesheets. Without it every page loses its layout, and the Next button on the row-or-column page can no
  longer be clicked.
- `font-src data:` allows the fonts embedded in the page; the browser fetches nothing for them. Only the
  row-or-column page needs it; without it, its two fonts fail to load. The other pages keep it, so that all pages
  carry the same line.

WebGL, the canvas and SVG references within the page need no rule. The build template of the row-or-column page
(outside the repo) carries the same line.

Checked with Playwright in headless Chromium, Firefox and WebKit, opened as a local file and through htmlpreview:
every page plays and steps to its end with no CSP violation and no console error; the embedded fonts load. A `fetch`
and an image added for this check are blocked by the browser before any request leaves, and are reported as
violations; the smoke tests record these reports as console errors, so such a page fails them (checked with the
tests' own recording). Leaving out any of the three allowing rules causes violations on at least one page (checked
in Chromium).

**htmlpreview** works with the policy. Its source,
[htmlpreview.js](https://github.com/htmlpreview/htmlpreview.github.com/blob/master/htmlpreview.js), last changed in
commit 787b673 of 2021-07-11; the live site served the same file on 2026-10-31, without a CSP of its own. It fetches
the page from raw.githubusercontent.com, adds a `<base>` element, renames every `<script` to
`<script type="text/htmlpreview"` so that it does not run, and writes the text into its own document with
`document.write`. From then on, the page's policy applies to htmlpreview's document. htmlpreview then inserts each
inline script again as a new `<script>` element, which `script-src 'unsafe-inline'` allows. Its own fetch of the
page happens before the policy exists. It would fetch external scripts and stylesheets after that, which the policy
would block, but the pages have none. Since the change is not on GitHub yet, the check used the live htmlpreview
but answered its request for the page with the local file: the pages work there, and the policy is in force. If
its fetch from raw.githubusercontent.com fails, htmlpreview fetches the page through a third-party proxy
(api.codetabs.com), before the policy exists; so the policy guards against our own mistakes, not against htmlpreview
or that proxy changing the page.

## Consequences

**Positive:** the browser blocks every load from the network for every reader, not only in the tests; a later edit
that adds one fails the smoke tests as before, since Chromium reports each blocked load as a console error.
**Negative:** a page that needs something new, e.g. an embedded image, has to extend the policy (`img-src data:`);
every new page has to carry the line; the policy has to be kept the same in all pages by hand.

## Out of scope & deferred

- A test that checks that every page carries the line (open; to be decided separately).
- The page `visualizations/call-through-dbms.html` (merge request !197, not yet on `main`) already carries the same
  line.
- What the policy does not stop: navigation (a click on a link, e.g. the row-or-column page's link to its notebook,
  `window.open`, a change of `location`, a meta refresh); hints that open connections in advance
  (`<link rel="dns-prefetch">`, `<link rel="preconnect">`); WebRTC; form submissions and `<base>` elements (these
  two rules, `form-action` and `base-uri`, are not covered by `default-src 'none'`). No page uses any of them.
- Reports of violations to a server (`report-uri` does not work in a `<meta>` policy, and there is no server).

## Alternatives rejected

- Hashes of each script and style (`'sha256-…'`) instead of `'unsafe-inline'`: every edit of a script would need a new
  hash, also in the build template; style attributes would need `'unsafe-hashes'`. They would stop injected scripts,
  but the pages take no input from outside.
- A policy per page (`font-src` only where fonts are embedded): one line for all pages is easier to copy and to
  check, and `font-src data:` loads nothing from the network.
- The policy as an HTTP header: there is no server of our own; GitHub and htmlpreview send none.
- `img-src data:` and similar rules in advance: no page needs them today.

<!-- notes below: skill never overwrites past this marker -->

Note 2026-11-03 (decision 034): the line gains `media-src data:`, so that a page can embed sound as `data:` URLs, as
the clock-scan page does for its synthetic voice. As with `font-src data:`, every page carries it, also a page without
sound, so that all pages keep one line; it loads nothing from the network. The pages of open merge requests
(`call-through-dbms.html` in !197, `clock-scan.html` in !201) get it on their next update.
