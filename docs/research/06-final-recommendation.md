# Deliverable 6: Final recommendation

## The recommendation

**Build Streetwise**, a native app that shows every street you have run or walked and how much of your city is left. It ranks first on the weighted model and is the only candidate where demand, a verified weakness in every rival, and your own daily use all line up.

It is a modest opportunity, not a large one. Nothing in this study looked like a large one for a solo developer.

## Personal fit: your interests against the findings

| Your interest | What the research found | Best candidate |
|---|---|---|
| Running | A real pocket: street completion, where native rivals are unreliable or single-city **[V]** | **Streetwise** |
| Lifting and bodybuilding | Saturated; Hevy and Strong each exceed 100,000 ratings **[V]** | SheetLift (no demand evidence) |
| Nutrition | Saturated; the category leader was bought by MyFitnessPal **[R]** | None |
| Investing and quant | Verified pain among option sellers, but hostile channels and data-licence costs **[V/R]** | WheelBook |
| Personal finance | Saturated or cloned | None for you (TipLedger serves a different user) |
| Cars | Every pocket already has five or more small entrants **[R]** | None |
| Software and AI automation | First-party tools cover it **[R]** | None |
| Careers | A gap that is closing; no proof speed matters | FirstPing |
| Gaming | Crowded where researched; partly unresearched | None found |
| Travel | Saturated | None |

## The five I would build, in order

### 1. Streetwise
- **Why it deserves attention:** one rival reached 1,033 ratings in six months serving a single city for free **[V]**. The web tool at the centre of the community lists about 92,000 registered users **[R]**. People already pay $30–50 a year for this **[V/R]**.
- **What existing apps get wrong:** they track live in the background and miss streets. "Consistently does not log blocks that I have clearly walked." "Only pieces tracked." **[V]** Or they are limited to New York, or are web tools with new, thin iOS apps.
- **Why users would switch:** their history appears on the first launch, and streets they ran actually count.
- **First users:** your run club and two others; a post of your own city map in local groups; 30 TestFlight runners in one metro.
- **Why someone would pay:** more cities, suggested routes over new streets, and neighborhood breakdowns, at $29.99/year.
- **First version:** import from Apple Health, street matching for one city, completion by neighborhood, a post-run "new streets" summary, a share card.
- **Eight-week build:**

| Week | Work |
|---|---|
| 1 | Technical spike: match your own workout routes to streets; test against streets you know. Check map-data licence and what Garmin and Strava write to Apple Health. |
| 2 | Python pipeline that builds a street pack for any city; publish packs for three metros. |
| 3 | iOS: Health import, on-device matching, progress stored locally. |
| 4 | Map view of covered and uncovered streets; city and neighborhood percentages. |
| 5 | Post-run processing, notification, "new streets" summary. |
| 6 | Share card; onboarding; paywall and one free city. |
| 7 | TestFlight with 30 runners; fix matching edge cases they report. |
| 8 | App Store submission, landing page, launch in one metro. |

### 2. WheelBook
- **Why it deserves attention:** four users across three 2026 threads describe the same gap in their own words **[V]**, and people pay $10–49 a month for weaker tools **[V/R]**.
- **What existing apps get wrong:** manual entry, and accounting that breaks on rolls.
- **Why users would switch:** a file import that produces correct per-cycle profit without typing.
- **First users:** a free web report that processes an export; options-income video creators. The main subreddit is closed to builders **[V]**.
- **Why someone would pay:** it replaces a spreadsheet they rebuild every year.
- **First version:** import for three brokers, cycle view, monthly income summary.
- **Build:** weeks 1–3 the reconciliation engine with a test corpus; weeks 4–6 the app; weeks 7–8 testers and launch.
- **Condition:** only if you sell options yourself. Otherwise you cannot judge correctness.

### 3. Parallel
- **Why it deserves attention:** the strongest pain in the study. 94 and 99 of the last 100 written reviews of two incumbents are 3 stars or lower **[V]**.
- **What existing apps get wrong:** price, reliability, and charging again to export one's own records **[V]**.
- **Why users would switch:** $39.99 a year and records they can always read.
- **First users:** ten family lawyers and mediators.
- **Why someone would pay:** many are required to use such an app.
- **First version:** uneditable messaging, custody calendar, verifiable export.
- **Build:** closer to 10–12 weeks, plus a backend you must keep running.
- **Condition:** only if you accept legal record requests and safety-sensitive support as part of the job. I would not start here alongside full-time work.

### 4. TipLedger
- **Why it deserves attention:** a live incumbent failure, documented days ago **[V]**, in a category where two apps hold about 10,000 ratings each.
- **What existing apps get wrong:** they lost data and look dated.
- **Why users would switch:** sync, export and an importer.
- **First users:** restaurant staff you know; this is the weak point, because you are outside that world.
- **Why someone would pay:** the incumbent already sells $19.99–29.99 plans **[V]**.
- **First version:** shift entry, calendar totals, iCloud sync and export.
- **Build:** three to four weeks. The cheapest way to learn the full App Store cycle.

### 5. FirstPing
- **Why it deserves attention:** you can test it in your own routine today, and its core is a polling backend, which is your strength.
- **What existing apps get wrong:** slow or infrequent checks; stale apps **[V]**.
- **Why users would switch:** measured speed.
- **First users:** your own cohort.
- **Why someone would pay:** a few months at $5.99 during a search.
- **First version:** watchlist, push alerts, status tracking.
- **Build:** six weeks.
- **Condition:** treat it as a small bet. I found no evidence that faster alerts change outcomes, and Simplify shipped a native app in August 2026 **[V]**.

## Why Streetwise over the others

1. **Demand is shown, not assumed.** A single-city free app drew a thousand ratings in six months. Among the other four candidates, only Parallel has stronger demand evidence.
2. **The weakness is specific and technical.** Rivals fail at the one thing the product is for. Fixing it requires a data pipeline and matching logic, which a weekend clone will not get right and which matches your backend skills.
3. **You are the user.** In a market where building is cheap, noticing reliability problems in daily use is the advantage.
4. **Growth does not depend on subreddits that ban promotion.** Maps are worth posting for their own sake, and run clubs meet in person.
5. **It can widen.** The same engine covers cycling, walking, hiking trails and travel, and a yearly recap.

## The case against it

- **Low severity.** This is motivation, not pain. It scored 5 of 10 on the criterion you weighted most.
- **Free competitors.** Sidewalk and Stomped charge nothing.
- **A capable rival.** Sidewalk's developer has shipped a successful app before and could add cities.
- **Platform risk.** Strava could ship this to its subscribers.
- **Base rates.** A median new subscription app earns about $72 a month after a year **[V]**.

## What would change my mind

- The week-one spike cannot reach 95% agreement with streets you know you ran.
- Fewer than 40% of 30 test runners return after three separate runs.
- Sidewalk launches nationally with tracking fixed before you ship.

If any of these happens, fall back to TipLedger for a fast, cheap launch, or to WheelBook if you trade options.

## Limits of this research

- The account's usage limit cut the research agents off twice. Six of twelve research areas were only partly covered, and two categories (personal analytics, digital organization) were not researched at all.
- Most secondary-source figures were read from search summaries, not the original pages.
- Reddit could be read only through an archive, so demand evidence leans on App Store reviews.
- Scores are my judgment. Download and revenue figures for small apps are not public; rating counts are a proxy for traction, not a measure of it.

## Next step

Per your instruction, the next step is for Opus to design UI mockups and a feature plan for Streetwise, for your review before any code is written.
