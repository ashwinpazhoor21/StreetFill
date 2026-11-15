# Deliverable 4: Top 10 startup proposals

These are the ten highest-scoring concepts from Deliverable 3. Evidence for the competitive claims is in `03-top-30-opportunities.md` and the research notes; tags are **[V]** verified, **[R]** reported, **[A]** assumption. Prices and success metrics proposed here are my recommendations, not market facts.

A caution before the proposals: ranks 4–10 are close in score and several have thin demand evidence. I say so in each "biggest risks" section.

---

## 1. Streetwise (score 6.85)

### A. Product concept
- **Pitch:** See every street you have ever run or walked, and how much of your city is left.
- **Target customer:** runners and walkers who record workouts with an Apple Watch or a running app and like completion goals.
- **Core problem:** street-completion apps either depend on web sync through Strava or track live in the background and miss streets.
- **Why alternatives fall short:** Sidewalk covers New York City only; its reviewers say it "consistently does not log blocks that I have clearly walked". Stomped users report runs where "only pieces tracked" **[V]**. CityStrides and Wandrer are web-first; their iOS apps are weeks to months old **[V]**.

### B. Product experience
1. Download, grant Apple Health access to workouts and routes.
2. The app reads past workouts on the phone and matches them to streets. Within a minute the user sees a map of their city with every street they have covered and a figure such as "31% of Evanston".
3. After the next run, a notification: "9 new streets. Southeast Evanston is now 64%."
4. The first benefit arrives before the user has done anything new, because their history already contains it.

### C. MVP features
- **Essential:** (1) import of workout routes from Apple Health and matching to streets for the user's city; (2) completion by city and neighborhood with a "new streets from this run" summary; (3) a shareable map card.
- **Later:** suggested routes over streets not yet covered, city and club leaderboards, Strava and Garmin import, Apple Watch complication, cycling and walking modes, yearly recap.

### D. Unique differentiator
Matching from the recorded workout route instead of live background tracking. It is the direct answer to the top complaint about both native rivals, and it gives an instant personal map from existing history.

### E. Growth strategy
- **First 100:** your own run club and two or three local ones; a post of your own city map in the city subreddit and local running groups (a map of "I've run 40% of Chicago" is content, not an ad); 30 TestFlight runners in one metro.
- **100 → 1,000:** launch one metro at a time so leaderboards feel alive; share cards carry the city name and percentage; pitch local news when a user finishes a neighborhood or city; search terms such as "run every street".
- **1,000 → 10,000:** club-versus-club coverage challenges (a group loop), city leaderboards, App Store editorial pitch built on HealthKit, widgets and Live Activities, then cyclists and walkers.
- **Why people share without incentives:** the map is a record of personal effort tied to a place, which is the same reason Strava activity cards and Flighty's travel summary get posted.

### F. Monetization
- Free: one city, full history, share cards.
- Paid, $29.99/year: unlimited cities and travel maps, route suggestions, neighborhood breakdowns, leaderboards.
- Evidence: CityStrides $50/year and Wandrer $40/year **[R]**; Fog of World $30 paid with 3,134 ratings **[V]**. The free native rivals cap what you can charge.

### G. Technical architecture
- **iOS:** SwiftUI, SwiftData, HealthKit (workouts and workout routes, with background delivery for new workouts), MapKit with a custom overlay for covered and uncovered streets.
- **Matching:** on the phone, against a compact street pack per city. Raw GPS routes never leave the device.
- **Backend:** Python pipeline that builds street packs from OpenStreetMap extracts into PostGIS and publishes them to object storage behind a CDN; a small FastAPI service for city lookup and, later, leaderboards.
- **Database:** PostGIS for the pipeline; CloudKit private database for each user's progress sync.
- **Authentication:** none for the MVP; Sign in with Apple when leaderboards arrive.
- **Notifications:** local notifications after each processed workout.
- **Analytics:** a privacy-focused SDK; RevenueCat or StoreKit 2 for subscriptions.
- **AI:** none needed.
- **To check in week one:** OpenStreetMap's licence terms for derived data; whether Garmin and Strava write routes into Apple Health (unverified); Strava's API rules, which restrict showing one user's Strava-derived data to others **[R]**.

### H. Validation experiment
1. One-week technical spike: match your own workout history to your city and check the result against streets you know you ran. Target: at least 95% agreement.
2. Put 30 local runners on TestFlight. **Success metric:** at least 40% open the app after three or more separate runs during weeks two and three, and at least 10 share a map unprompted.

### I. Biggest risks
- Sidewalk adds cities and fixes tracking, or Strava ships street completion.
- The audience is modest: CityStrides took years to reach about 92,000 registered users **[R]**.
- Street matching has many edge cases (GPS drift, parallel streets, private roads, map errors).
- The problem is motivation, not pain, so willingness to pay is limited.

---

## 2. Parallel (score 6.20)

### A. Product concept
- **Pitch:** A co-parenting record both parents can afford: messages, calendar and expenses that cannot be edited after the fact.
- **Target customer:** separated parents, including those ordered by a court to use a monitored app.
- **Core problem:** all three incumbents now charge, and their recent reviews are overwhelmingly negative **[V]**.
- **Why alternatives fall short:** price (reviewers cite "$100 a year" and "40 a month"), bugs, and paying again to export records **[V]**.

### B. Product experience
Download → create a family → invite the other parent by link → send the first message, which is timestamped and shows when it was read → export a PDF record at any time.

### C. MVP features
- **Essential:** (1) messaging that cannot be edited or deleted, with read receipts; (2) shared custody calendar with swap requests; (3) verifiable PDF export.
- **Later:** expense tracking and reimbursement, a tone check before sending, read-only access for lawyers.

### D. Unique differentiator
Free lifetime read access and export of your own records, with a price under half the incumbents'. That answers the complaint that parents are locked out of their own history.

### E. Growth strategy
- **First 100:** ten family lawyers and mediators in your state, with free professional accounts; answers in co-parenting communities where rules allow.
- **100 → 1,000:** each user brings the other parent; search for "[incumbent] alternative".
- **1,000 → 10,000:** professional referrals and court-services lists.

### F. Monetization
$39.99/year per parent, with a fee waiver option. Payment is close to compulsory for this audience, though resented.

### G. Technical architecture
- **iOS:** SwiftUI.
- **Backend:** required. Supabase (Postgres with row-level security); an append-only message table where each record includes a hash of the previous one.
- **Authentication:** Sign in with Apple plus email.
- **Notifications:** APNs.
- **Analytics:** minimal, no message content.
- **AI:** none in the MVP.

### H. Validation experiment
Interview ten family lawyers or mediators with a one-page description. **Success metric:** five say they would recommend it to clients, and at least one court in your county confirms it would accept the export.

### I. Biggest risks
- Courts name specific apps in orders.
- Record requests, subpoenas and user-safety incidents land on one person with a day job.
- You are not the user. Incumbents can cut prices.

---

## 3. WheelBook (score 6.00)

### A. Product concept
- **Pitch:** Drop in your broker export and see what each wheel cycle actually paid you.
- **Target customer:** people selling cash-secured puts and covered calls weekly.
- **Core problem:** brokers report profit per trade; a wheel cycle spans puts, assignment, calls and rolls.
- **Why alternatives fall short:** trackers need manual entry or break on rolls, in users' own words **[V]**.

### B. Product experience
Download → import a broker file from the Files app → the engine groups trades into cycles → first screen shows premium collected this month, profit per cycle and adjusted cost basis.

### C. MVP features
- **Essential:** (1) import and reconciliation for three brokers; (2) cycle view with rolls, assignments and adjusted basis; (3) monthly income summary with a share card.
- **Later:** broker sync, tax-lot view, expiry reminders, more brokers.

### D. Unique differentiator
Correctness on rolls and assignments, shown leg by leg so the user can audit it.

### E. Growth strategy
- **First 100:** a free web page that turns an export into a cycle report; options-income video creators; posting your own monthly cards.
- **100 → 1,000:** search pages around cost-basis questions; creator affiliates.
- **1,000 → 10,000:** broker sync and broker-community partnerships.
- The main subreddit removes builder posts **[V]**, so it is not a channel.

### F. Monetization
Free for one account and 30 days of history; $79/year or $9.99/month. A direct competitor charges the same **[V]**.

### G. Technical architecture
- **iOS:** SwiftUI, SwiftData; parsing on the device so files stay private.
- **Backend:** none for the MVP. A Python reference implementation with a test corpus of exports guards correctness.
- **Database:** CloudKit sync.
- **APIs:** no market data, which avoids a display licence; broker sync later costs $100/month plus $1–2 per user **[V]**.
- **AI:** optional on-device model to map unfamiliar file columns.
- **Publishing:** under an LLC, given Apple's rule on finance apps **[V]**.

### H. Validation experiment
Ship the free web report first. **Success metric:** 200 exports processed and 40 email sign-ups in four weeks.

### I. Biggest risks
- At least 17 existing tools and no channel to reach buyers.
- Several users say a spreadsheet or the broker is enough **[V]**.
- Each broker's format changes without notice.
- It only works as a dogfood project if you sell options yourself.

---

## 4. TapeJournal (score 5.95)

### A. Product concept
- **Pitch:** Log a trading session in ten seconds and see your month as a P&L calendar.
- **Target customer:** active day and swing traders.
- **Core problem:** web journals are priced for professionals and are weak on the phone.
- **Why alternatives fall short:** TraderSync's iOS app is rated 2.71; the fastest-growing native journal has no broker import and no update since May 2026 **[V]**.

### B. Product experience
Download → enter today's result and a note → the calendar fills in → weekly statistics appear after five entries.

### C. MVP features
- **Essential:** (1) fast entry with tags and screenshots; (2) P&L calendar and statistics; (3) file import for two brokers.
- **Later:** options-aware grouping (shared with WheelBook), prop-firm rule tracking.

### D. Unique differentiator
Import on the phone, and treatment of multi-leg option positions as one trade.

### E. Growth strategy
Calendar screenshots are already a habit among traders. First 100 from two or three trading communities you belong to; then creators and search.

### F. Monetization
$4.99/month, $29.99/year, $59.99 lifetime, matching the nearest competitor **[V]**.

### G. Technical architecture
On-device only: SwiftUI, SwiftData, CloudKit. No market data. No AI.

### H. Validation experiment
TestFlight with 30 traders. **Success metric:** 40% log at least eight sessions in two weeks.

### I. Biggest risks
- Two competitors already have traction.
- Most new day traders stop trading.
- Little separates this from WheelBook; build one engine and one product, not two.

---

## 5. FirstPing (score 5.90)

### A. Product concept
- **Pitch:** Add your target companies and get a push within minutes when they post a role that fits.
- **Target customer:** job seekers with a list of 10–50 employers, especially new graduates in tech.
- **Core problem:** job-board alerts arrive late or bury the posting.
- **Why alternatives fall short:** the three indie apps have seven ratings between them; one polls every 45 minutes and has not shipped since June **[V]**.

### B. Product experience
Download → pick companies and keywords → first alert the same day → tap "applied" to track it.

### C. MVP features
- **Essential:** (1) watchlist built from public career-page feeds; (2) push alerts with filters; (3) one-tap application status.
- **Later:** harder career sites, cohort sharing, reminders to follow up.

### D. Unique differentiator
Measured and published alert latency, in a native app with a tracker.

### E. Growth strategy
- **First 100:** your own cohort and class group chats; a public, auto-updated list of new postings generated by the same crawler.
- **100 → 1,000:** bootcamps and campus groups.
- **1,000 → 10,000:** search pages per company.

### F. Monetization
Free for three companies; $5.99/month for unlimited and instant alerts. Users leave when hired.

### G. Technical architecture
- **iOS:** SwiftUI, SwiftData.
- **Backend:** FastAPI, Postgres, polling workers; this is the core of the product and matches your strengths.
- **Authentication:** Supabase Auth or Sign in with Apple.
- **Notifications:** APNs.
- **AI:** optional matching of postings to a profile.

### H. Validation experiment
Run the alerts as an email or chat bot for 50 job seekers for two weeks. **Success metric:** 60% keep alerts on and at least 10 say they would pay.

### I. Biggest risks
- No evidence yet that faster alerts change outcomes.
- Simplify shipped a native app in August 2026 and already has the audience **[V]**.
- Career-page formats change; polling needs constant upkeep.

---

## 6. SheetLift (score 5.50)

### A. Product concept
- **Pitch:** Paste your coach's spreadsheet and lift from a clean tracker that fills it in for you.
- **Target customer:** lifters following a program delivered as a Google Sheet.
- **Core problem:** editing a spreadsheet between sets.
- **Why alternatives fall short:** mainstream trackers need the program retyped; the one importer has no ratings and no update since March 2026 **[V]**.

### B. Product experience
Download → share the sheet link → review the parsed program → start today's session with weights prefilled.

### C. MVP features
- **Essential:** (1) import with a review step; (2) workout mode with rest timer and prefilled loads; (3) export of results back to the coach.
- **Later:** a coach plan, templates for well-known free programs.

### D. Unique differentiator
The round trip: the coach's sheet goes in, completed numbers come back out.

### E. Growth strategy
First 100 through coaches who sell spreadsheet programs; each coach brings clients. Templates for popular free programs give a search entry point.

### F. Monetization
$29.99/year. The category is anchored near $24/year **[R]**.

### G. Technical architecture
SwiftUI, SwiftData, HealthKit. Parsing with Apple's on-device or hosted model, which costs nothing for a small developer **[V]**, with user review of the result. No backend at first.

### H. Validation experiment
Convert 20 lifters' sheets by hand. **Success metric:** 12 use the result for six or more sessions in two weeks.

### I. Biggest risks
- No demand evidence was found.
- Spreadsheets vary without limit.
- Hevy or Strong can add import.

---

## 7. TipLedger (score 5.35)

### A. Product concept
- **Pitch:** Log tonight's tips in ten seconds and never lose your history.
- **Target customer:** servers and bartenders.
- **Core problem:** the long-standing leader lost some users' multi-year history in November 2026 **[V]**.
- **Why alternatives fall short:** dated apps, and no easy way to bring old data across.

### B. Product experience
Download → import an existing export or start fresh → enter tonight's tips → see hourly rate and weekly total.

### C. MVP features
- **Essential:** (1) shift entry for cash and card tips, tip-out and hours; (2) calendar with totals and hourly rate; (3) iCloud sync, export and import.
- **Later:** shared tip-out among coworkers, multi-job reports, year-end summary.

### D. Unique differentiator
Trust: automatic iCloud sync, one-tap export, and an importer.

### E. Growth strategy
Coworkers on the same shift are the channel. You are not in this world, so reaching the first 100 will be harder than for other ideas.

### F. Monetization
Free core; $19.99/year for extras. The incumbent sells plans at $19.99–29.99/year **[V]**.

### G. Technical architecture
SwiftUI, SwiftData, CloudKit. No backend, no AI. Avoid anything that reads as tax advice.

### H. Validation experiment
Ship in three to four weeks. **Success metric:** 100 organic installs and 30 users still logging in week four, within six weeks of launch.

### I. Biggest risks
- Low price ceiling and free rivals.
- Newer apps are already absorbing displaced users.
- No personal fit.

---

## 8. Mothertongue (score 5.35)

### A. Product concept
- **Pitch:** Speaking practice for people who grew up hearing the language.
- **Target customer:** adults who understand a family language but cannot speak it comfortably. Start with one language.
- **Core problem:** apps start from zero and teach formal register.
- **Why alternatives fall short:** the closest product does not list several South Indian languages **[V]**.

### B. Product experience
Download → a listening check places the user → a short role-play ("call your grandmother") → feedback on what was said.

### C. MVP features
- **Essential:** (1) placement by comprehension; (2) spoken role-plays in family situations; (3) a phrase bank checked by native speakers.
- **Later:** more languages, reading and script, family-recorded phrases.

### D. Unique differentiator
Starting from comprehension, in colloquial register, with speech recognition chosen for that language.

### E. Growth strategy
Diaspora social pages, family chat groups and cultural associations.

### F. Monetization
$9.99/month or $59.99/year.

### G. Technical architecture
- **iOS:** SwiftUI.
- **Backend:** FastAPI for speech and model calls.
- **APIs:** a speech-recognition vendor that handles the target language; a benchmark reports a mainstream model failing on Malayalam **[R]**.
- **AI:** central to the product. Explicit consent before audio leaves the device **[V]**.

### H. Validation experiment
A paid pilot over voice notes with 30 people. **Success metric:** 15 complete six sessions in two weeks and 8 pay $10.

### I. Biggest risks
- Demand rests on three reviews.
- Each language is a small market.
- Speech costs per minute; quality needs native reviewers.

---

## 9. ShelfLedger (score 5.20)

### A. Product concept
- **Pitch:** See every figure preorder, what it costs, and which month it hits your card.
- **Target customer:** anime-figure collectors with many open preorders.
- **Core problem:** preorders sit across several shops with release dates that move.
- **Why alternatives fall short:** the main catalogue site has no app; two new apps have one rating each **[V]**.

### B. Product experience
Download → add three preorders → see a month-by-month payment calendar.

### C. MVP features
- **Essential:** (1) quick preorder entry; (2) monthly payment calendar and budget; (3) collection shelf with photos.
- **Later:** share extension for shop pages, delay alerts, collection value.

### D. Unique differentiator
The budget calendar.

### E. Growth strategy
Collector communities and video creators; shelf and "monthly haul" cards.

### F. Monetization
$14.99/year or $24.99 lifetime.

### G. Technical architecture
SwiftUI, SwiftData, CloudKit. No backend. User-entered data, so no dependence on another site's catalogue.

### H. Validation experiment
Publish a spreadsheet template with a waitlist link. **Success metric:** 100 waitlist sign-ups in three weeks.

### I. Biggest risks
- Small audience.
- A spreadsheet may be enough.
- The catalogue site could ship its own app.

---

## 10. PatchDay (score 5.10)

### A. Product concept
- **Pitch:** Know which patch, which dose and which side today.
- **Target customer:** women on menopausal hormone therapy.
- **Core problem:** twice-weekly patches and cyclic doses are easy to lose track of.
- **Why alternatives fall short:** the largest app is symptom-first and has calendar complaints **[V]**.

### B. Product experience
Download → enter the regimen → today's card shows what is due and where.

### C. MVP features
- **Essential:** (1) regimen schedule with reminders; (2) application-site rotation; (3) symptom log with a clinician report.
- **Later:** Apple Health integration, trend views.

### D. Unique differentiator
Regimen first, symptoms second.

### E. Growth strategy
Community recommendation and clinician referral.

### F. Monetization
$19.99/year.

### G. Technical architecture
SwiftUI, SwiftData, local notifications. No backend. Schedule logging only, never dose advice, given App Review's treatment of dose tools **[V]**.

### H. Validation experiment
Fifteen interviews. **Success metric:** ten currently track on paper or in notes and say they would switch.

### I. Biggest risks
- Apple is reported to be adding menopause logging to Health **[R]**.
- Several 2026 entrants.
- You are not the user.
