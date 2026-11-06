# 039 — Project logo for the README and the project avatar
**Date:** 2026-11
**MR:** https://gitlab.cs.uni-saarland.de/bigdata/dbsys/explaindb/-/merge_requests/222
---
## Context

ExplainDB had no logo: the README starts with a text heading, and the GitLab project and the GitHub organisation
have no avatar. The logo should be recognisable at avatar size (16–48 px) and readable in the light and dark themes
of GitLab and GitHub. Of several drafts, the user chose "A": a database cylinder under a magnifying glass, with a
small query-plan tree inside the lens. The colours are those of the visualization pages (dark ground, light ink,
green accent).

## Decision

One SVG holds the logo: the mark centred on a dark rounded tile. Because the mark always sits on its own tile, it
reads the same in every site theme, and the lens can hide the cylinder with a fill in the tile colour. All colours
are presentation attributes; the SVG has no style sheet, no script and no references, and carries the AGPL header
as a comment like the HTML pages.

The README shows this SVG left-aligned above the title, as an HTML block followed by a blank line. The avatar is a
512 × 512 PNG exported once from the same SVG with a filled background (a full square, because GitLab and GitHub
round avatars themselves); CONTRIBUTING.md names the export command.

A repository test checks that the SVG stays safe to embed, that the PNG is 512 × 512, and that the README shows
the logo before the title with a meaningful alt text; each check is also run on hand-written inputs it must
reject. The user checks the README rendering on the merge-request branch before the merge. After the merge, the
GitLab project avatar is set via the API with the user's consent; the GitHub organisation avatar is set by hand.

## Consequences

**Positive:** one source file for README and avatar, so nothing can drift; theme-proof without relying on
browser behaviour; the test catches unsafe or broken embedding.

**Negative:** the logo always shows a dark tile, also on a light page; the PNG is exported by hand and the test
cannot tell whether it still matches the SVG; the plan tree in the lens is only one or two pixels at the smallest
avatar sizes.

## Out of scope & deferred

- A transparent, theme-aware variant via `<picture>` (GitHub rewrites it to the site theme).
- A wordmark with the text converted to outlines.
- A favicon for the visualization pages (needs a simplified mark).
- The logo in the intros of the rendered videos.
- A GitHub social preview image (1280 × 640).

## Alternatives rejected

- One SVG whose colours switch with `prefers-color-scheme`: inside an `<img>` it follows the operating system or
  browser, not the site theme, so the mark can become nearly invisible.
- A transparent mark whose lens hides the cylinder with an SVG mask: only needed for a transparent variant.
- The wordmark as SVG `<text>`: web fonts do not load in an SVG shown via `<img>`.
- A script that exports the PNG: too much for a single asset.

## Scope-shift 2026-11-06

After seeing variant A in place, the user found it too plain and asked for more ideas. After several rounds of drafts
(a magnifier, a speech bubble, a mortarboard, the robot of the house animation) the user chose a wordmark: the orange
robot of the house animation sits on the writing line in place of the letters "ai" of ExplainDB, which stand in full
size on its belly; it wears a mortarboard, its legs dangle over the edge of the line, and its head casts a soft
shadow on its body so that head and body stay apart.

Because letters and line change colour with the theme, the logo now comes as two files, one for light and one for
dark backgrounds, each on its own background so that it stays readable if a site shows the wrong one; the README picks
one with `<picture>` and `prefers-color-scheme`. The wordmark is set in Space Grotesk Bold (SIL Open Font License) and
converted to outlines, so the SVG needs no font inside an `<img>`; the shadows are plain shapes with opacity, not SVG
filters; for them and the mortarboard the repository test now also allows the element `polygon` and the
attributes `points` and `opacity`. The avatar is the robot alone on a dark square, exported to PNG from its own SVG.
The files were generated once from the geometry of the HTML drafts; later changes are made in the SVGs directly.

This replaces parts of the text above: there is no longer one source file for README and avatar, the logo no longer
always shows a dark tile, and there is no plan tree in a lens any more. Two deferred items are now built in part: the
wordmark with the text converted to outlines, and the `<picture>` that picks a logo for the theme (with two logos on
their own backgrounds instead of one transparent logo). Of the note below the marker, the first sentence still
holds; the second does not: the light logo, the dark logo and the avatar each hold their own copy of the robot,
they are kept in step by hand, and the test cannot tell whether they match.

<!-- notes below: skill never overwrites past this marker -->

**Note (2026-11-06, implementation):** the export command is kept in one place only, the SVG's header comment;
CONTRIBUTING.md points to it instead of naming it. "Nothing can drift" under *Consequences* holds for README and
avatar source only: the PNG is exported by hand and can fall behind the SVG, as the negative consequences say.
