# StreetFill

Every street you've run, and the ones you haven't.

StreetFill is an iPhone app (in development) that reads the runs already in Apple Health, matches each recorded route to your city's streets on the phone, and shows how much of your city and each neighborhood you've covered. It then plans runs over streets that are new to you, with terrain and scenery preferences and photo previews of what you'll pass. A friends release follows, where you compare the neighborhoods you've each covered.

- **Landing page:** https://ashwinpazhoor21.github.io/StreetFill/
- **Design mockups:** https://ashwinpazhoor21.github.io/StreetFill/mockups/
- **Product and build plan:** [docs/product/product-plan.md](docs/product/product-plan.md)
- **Market research:** [docs/research/](docs/research/)

## Status

Phasing follows **Option B** in the product plan (section 12): v1 with Discover in about 12 weeks, Friends as v1.1 around week 19.

| Week | Milestone | Status |
|---|---|---|
| 1 | Matching spike: Python reference matcher, measured against hand-labelled streets (Gate 1) | **In progress** |
| 2 | Street-pack pipeline v2 (paths, elevation, scenery, highlights) | Not started |
| 3 | Route-generation spike (Gate 2) | Not started |
| 4–12 | iOS app, TestFlight, launch | Not started |

## Repository layout

```
docs/               GitHub Pages site (landing page) and all product documentation
  index.html        Landing page
  mockups/          UI mockups (self-contained HTML)
  product/          Product and build plan
  research/         Market research behind the product decision
  assets/screens/   Mockup screenshots used on the landing page
pipeline/           Python: street-pack builder, reference matcher, evaluation (week 1)
```

## Week 1: run the matching spike

See [pipeline/README.md](pipeline/README.md).

## Landing page waitlist

The waitlist form posts to `WAITLIST_ENDPOINT` at the bottom of `docs/index.html`. It is empty until a form service is chosen (for example Formspree, Tally or Basin); until then the form tells visitors sign-ups open soon.
