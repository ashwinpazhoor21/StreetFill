# StreetFill: product and build plan (v1, revision 2)

**Date:** 2026-11-15
**Status:** revision 2, approved by the owner on 2026-11-15 with **Option B** phasing (section 12). Open decisions in section 13 other than D3 are still open.

**What changed in revision 2:**
- New working name, **StreetFill** (an earlier draft of this revision used Footfall). "Streetwise" is taken.
- Repositioned as discovery plus friendly competition.
- Three features added:
  - **Discover**: generated runs with terrain and scenery preferences
  - **Highlights** with images
  - **Friends**: compare areas with friends
- A phasing choice between two options. I recommend Option B: v1 includes Discover, and Friends is the next release.

**Companion file:** [`../mockups/index.html`](../mockups/index.html) (also published on the project site). Screen numbers (S01–S25) match the mockup frames, and each new screen is marked with its release.

**How to read the labels**
- **[Research]**: from the research files in [`../research/`](../research/) (mainly `06-final-recommendation.md`, `04-top-10-proposals.md`, `03-top-30-opportunities.md`). The underlying source notes (including `11-platform-economics.md`) are kept outside this repository.
- **[Research 2026-11-15]**: checks the coordinator ran today on the name, existing route generators, and Look Around imagery.
- **[Apple docs]**: checked today against Apple's HealthKit documentation.
- **[Unverified]**: from memory or inference. Check it before relying on it.
- **[Assumption]**: a design choice or estimate of mine. You can change it.
- **[Tune]**: a starting value for a spike. Expect it to change.

Sample data in this plan and in the mockups (Chicago; a runner based in North Center; friends named Priya, Marcus and Jen; every percentage and mile count) is invented to show the design.

---

## 1. Product summary

**What it is.** A native iPhone app with three parts:
- **See where you've run.** Every street you have run or walked is mapped from your Apple Health history, with completion percentages for your city and each neighborhood.
- **Get runs that take you somewhere new.** Discover generates loops over streets and areas that are new to you. You choose distance, terrain (flat to hilly), how much of the route is new, and scenery (waterfront and beaches, parks, landmarks). Each option shows the highlights you will pass, with a photo.
- **Compare with friends.** See which neighborhoods only you, only a friend, or both of you have run. Friends-only leaderboards and a feed of new areas reached. Coming in the release after v1.

**Who it is for.** Runners and walkers who record workouts on an Apple Watch or with a running app that writes to Apple Health, who like completion goals and exploring their city. The first users are the owner's run club, two or three other clubs, and 30 TestFlight runners in one metro [Research].

**The foundation, and why it is different.**
1. **Matching from the finished workout's recorded route** in Apple Health, not live background GPS. Missed streets are the native rivals' top complaint [Research]. It also means years of history become a map on first launch.
2. **Routes generated from your own history.** Route generators with flat-or-hilly and scenery controls already exist: Trail Router, RunCulture, Roovr, and Strava's paid route builder [Research 2026-11-15]. So those controls are expected, not special. The search found **no** generator that uses the runner's own history [Research 2026-11-15]. StreetFill's difference is routes over streets that are *new to you*, with previews of what you will see.
3. **Friends compare areas, not pace.** Competition on exploration ("kinda similar to Beli but for running", the owner's words), not on speed.

**Privacy stance (updated).** Matching and route generation happen on the phone. Raw GPS routes never leave the device. Location permission is asked **only when you tap** "Use my location" or open the follow-along map, and only while the app is in use. When Friends ships, only area-level summaries are uploaded by default, and only after explicit consent.

**Out of scope for v1** (under the recommended Option B):
- Friends, accounts and any server (planned as v1.1)
- Public profiles and public leaderboards (not planned)
- Turn-by-turn voice guidance and background location
- Apple Watch app
- Strava, Garmin or GPX/FIT *import*
- Cycling mode
- Yearly recap
- AI features
- Android, web app

---

## 2. Feature specification

Release tags use Option B (section 12): **[v1]** or **[v1.1]**.

### F1. Import workout routes from Apple Health and match them to streets [v1]

**User story.** As a runner with years of Apple Watch runs, I want the app to read my past and future workouts and work out which streets and paths I covered, without recording anything new.

**Behavior**
1. After read access is granted (S02), an anchored query reads workouts of the counted types: running, walking and hiking [Assumption]. Each workout's route locations are read in batches with `HKWorkoutRouteQuery` [Apple docs].
2. Workouts without a route are recorded as "no route" and counted in Settings.
3. **Home city detection.** Workout start points from the last 12 months are clustered on the device and checked against the city manifest. The app proposes a city and the user confirms it. If no supported city matches, the "not yet supported" state appears.
4. The city pack downloads, then workouts are matched newest first while the map fills in (S03).
5. The first import continues in the background as a continued-processing task [Research: `BGContinuedProcessingTask` exists in iOS 26; exact behavior Unverified].
6. An observer query with background delivery handles new workouts. HealthKit's completion handler must be called, or HealthKit stops sending updates after three failed attempts. Background delivery needs the Background Delivery entitlement and does not work in the Simulator [Apple docs].
7. Deleted workouts are reported by the anchored query, and their contribution is removed.
8. Duplicate workouts (80% or more time overlap [Tune]) count toward coverage but get no second notification.
9. Workouts crossing a city boundary are matched against every downloaded pack they touch.
10. **New:** named paths and trails are matched as well. They get their own progress (section 5.2) and do not change the street percentage.
11. **New:** if a finished workout follows 70% or more of a saved Discover route [Tune], that route is marked "Run" and moves to the Been list.

**Acceptance criteria**
- 1,000 workouts with routes import in 60 s or less on an iPhone 13 or newer, with the first streets visible within 10 s [Assumption, based on the research's "within a minute"].
- Matching agrees with the owner's hand-labelled set at 95% or better (gate 1).
- A new Watch workout updates the map, widget and notification within 15 minutes of first unlock after syncing, in 5 of 5 runs.
- Deleting a workout in Health removes its streets within one app open.
- No GPS coordinate leaves the device; checked with a network log.
- Denied access or no workouts leads to the S03 "no workouts found" state.

### F2. Completion by city and neighborhood, with a "new streets from this run" summary [v1]

**User story.** As a runner, I want to see how much of my city and of each neighborhood I have covered, and what each run added.

**Behavior**
1. **Headline** [Assumption]: percentage of runnable *street* length covered ("8.4% of Chicago"). Secondary figures: miles, and streets complete.
2. **New: Paths & trails.** A separate list per city of named paths and trails (for example "Lakefront Trail 74%") and miles of path covered. Paths do not change the street percentage, so it stays comparable with other street-completion apps.
3. **Definitions.** A street is a named street inside a city; inside a neighborhood, it means the part inside that neighborhood. A street is complete at 90% or more of its checkpoints [Tune].
4. **Neighborhoods (S05)** now opens from the Map tab's bottom sheet; see the navigation note in section 3. Detail (S06), street sheet and disputes (S07), Runs (S08) and post-run summary (S09) are unchanged.
5. **Notification:** "9 new streets on your Morning Run. North Center is now 61%."
6. **Widget (S15):** city percentage, top neighborhood, mini-map.

**Acceptance criteria**
- The city percentage matches the Python reference to 0.1 points.
- Neighborhood percentages, weighted by length, sum to the city percentage.
- The notification, summary and widget show the same numbers.
- Covered and uncovered are distinguishable in grayscale.

### F3. Shareable map card [v1]

**User story.** As a runner, I want to post a clean image of my progress.

**Behavior and acceptance criteria**
- Unchanged from revision 1.
- Scopes: run, neighborhood, city. Formats: square and story. Light or dark.
- Coverage only, never a single run's route. Includes "© OpenStreetMap contributors".
- Rendered on the phone in 1 s or less. Always free.

### F4. Discover: generated runs that take you somewhere new [v1]

**User story.** As a runner who is bored of the same loops, I want the app to suggest a few runs from a start point I choose, at the distance and terrain I want, that cover streets and areas I have not run, so I see new parts of my city.

**Inputs (S16)**

| Input | Options | Default |
|---|---|---|
| Start point | Pick on the map (drag a pin); one of my usual starts (clustered from my own workout start points, on device, no location permission needed); "Use my location" (asks for When-In-Use permission on first tap) | Most frequent recent start |
| Length | Distance (1–20 mi) or time (converted on device using my median pace for that activity from Health) | 5 mi |
| Shape | Loop or out-and-back | Loop |
| Terrain | Slider: Flat · Rolling · Hilly | Rolling |
| New to me | Slider: 0–100% target share of the route that is new | 60% |
| Scenery | Chips, multi-select: Waterfront & beaches · Parks & green · Landmarks | None |
| Quiet streets | Toggle; avoids main roads where it can | On |

Quiet streets earns its place: it costs nothing (road class is already in the pack), and it is the main safety lever for a route the runner has never seen.

**Outputs (S17).** Up to three distinct options, each with:
- name (built from the main highlight or neighborhood, for example "Lakefront to Montrose Beach")
- distance and elevation gain
- share of the route that is new
- new neighborhoods touched, and the expected gain in neighborhood percentage
- up to three highlight thumbnails
- a mini-map

**Route detail (S18)**
- Map with the route; new parts drawn differently from parts run before.
- Elevation profile with highlight markers.
- Highlight photo strip in route order.
- New streets list.
- "Start" (S20), "Save to Want to run", "Regenerate", share.

**Behavior**
1. Generation runs on the phone from the street pack and the user's own coverage (section 6). Nothing about the request leaves the device.
2. If the area cannot meet a preference, the app says so plainly. For example, Chicago is flat, so "Hilly" shows "Hilliest option nearby: +120 ft" rather than pretending.
3. If fewer than three distinct routes exist (dense waterfront, small start areas), fewer are shown.
4. Saved routes go to the **Want to run** list. When a finished workout matches 70% or more of a saved route, it moves to **Been** (F1 step 11).

**Acceptance criteria**
- Three options for a 5 mi loop appear in 2 s or less on an iPhone 13, and 4 s or less for 13 mi [Tune].
- Every option's distance is within ±5% of the target [Tune].
- The new share is within ±10 points of the target where the area allows. Otherwise the app labels it, for example "Most new streets available: 42%".
- No option uses an excluded way (motorway, private, `foot=no`, construction).
- The three options share no more than 40% of their length with each other [Tune].
- Gate 2 (route quality) is passed: the owner rates 20 routes (section 14).
- Works offline once the city pack is downloaded. Photos and Look Around need a network, and the route itself does not.

### F5. Highlights with images [v1]

**User story.** As a runner choosing a route, I want to see what I'll pass (the beach, a landmark, a park) so I pick the run that sounds best.

**Behavior**
1. **Highlights** are named places baked into the city pack from OpenStreetMap tags (section 6.6). A highlight belongs to a route if it lies within 60 m of it, or within 150 m for large features such as beaches and parks [Tune]. They are listed in route order with the distance along the route.
2. **Images, in order of preference:**
   1. A freely licensed photo (for example from Wikimedia Commons via the OSM feature's Wikidata or Commons link), mirrored to StreetFill's CDN by the pipeline. The author and licence are shown on the image.
   2. A **Look Around** street-level snapshot from Apple (`MKLookAroundSnapshotter`, iOS 16.0+) [Research 2026-11-15].
   3. An illustrated category placeholder (beach, park, landmark, water, historic) with the name.
3. **Highlight card (S19)**
   - photo with attribution
   - name, category, one-line description (from Wikidata where present [Unverified: Wikidata descriptions are CC0])
   - "mile 2.4 of this route" and the elevation there
   - "Street view" (interactive Look Around, where available)
   - "Add to Want to run"
4. **Elevation profile** on S18. Distance on the x-axis, elevation on the y-axis, total gain, numbered highlight markers.

**Acceptance criteria**
- Every highlight shows an image or the illustrated placeholder; never an empty box.
- Every photo shows its author and licence wherever it appears.
- Look Around is requested only on S18 and S19, not when listing options, and can be switched off in Settings.
- Images load lazily; route options never wait for images.

### F6. Friends: compare the areas you have covered [v1.1]

**User story.** As a runner whose friends also use the app, I want to see which neighborhoods each of us has run, compete on exploring, and see when friends reach somewhere new, without anyone seeing my routes or where I live.

**What translates from Beli** [Assumption: my understanding of the restaurant app Beli, a "been" list, a "want to try" list, a friend feed and rankings among friends; not researched]:

| Beli idea | StreetFill version |
|---|---|
| Been list | **Been**: neighborhoods reached, named trails completed, highlights passed, Discover routes run |
| Want to try | **Want to run**: saved routes, neighborhoods and highlights. Private by default; share items one at a time. |
| Friend feed | Feed of new areas reached and milestones, posted in a daily batch |
| Rankings among friends | Leaderboards among friends by city or neighborhood: percentage, and new streets this week or month |
| Pairwise "which did you like more" ranking | Not adopted. Exploration is measurable, so there is nothing to rank by taste. "Rate this route" could come later. |

**Behavior**
1. **Sign in** (S21) with Sign in with Apple. Before anything is uploaded, an explicit consent step explains what is shared (below).
2. **Invite** (S24): a personal invite link and code. Shared through the share sheet or shown as a QR code. Accepting creates a two-way friendship; either side can remove it.
   - If the friend does not have the app, the link opens the App Store. After install, the friend enters the code shown on the web page, or taps the link again [Assumption: avoids third-party deferred deep-linking SDKs].
3. **Friends home** (S22): segmented **Feed** | **Leaderboard**.
   - Feed items: "Priya reached Rogers Park (new neighborhood)", "Marcus passed 25% of Logan Square", "Jen finished the Lakefront Trail". One-tap cheer. No comments in v1.1, which avoids moderating free text.
   - Leaderboard: scope (a city, or a neighborhood) × metric (percentage, or new streets this week or this month).
4. **Compare** (S23):
   - three groups: "Only you", "Both", "Only Priya", by neighborhood count
   - neighborhood-by-neighborhood rows with both percentages
   - "Run there next" opens Discover with the start in a neighborhood only the friend has run
   - with street-level sharing on (both sides opted in), a combined map
5. **Sharing and privacy settings** (S25), described next.

**Uploaded by default** (area level, after consent):
- display name and emoji avatar
- per city and per neighborhood: covered percentage (0.1 precision), streets complete, and the month first reached
- per week: count of new streets and new neighborhoods
- feed events

Uploads happen at most once a day, with dates only and no times of day.

**Uploaded only by explicit choice:**
- a street-level coverage map: a bitmap of edge ids, never GPS, with the **home zone removed on the device** before upload
- items from Want to run

**A friend can never see:**
- routes or any GPS point
- run dates, times, pace, distance per run, or heart rate
- your home zone, or streets inside it
- your Health data of any kind
- anything at all if you remove them or block them

**Home zone.** Set on a map; default radius 0.25 mi (400 m) [Tune], adjustable from 0.1 to 0.6 mi. Streets inside are never uploaded, and feed events about streets inside it are suppressed. You can also hide whole neighborhoods from friends.

**Friends-only.** No public profiles, no public leaderboards, no search by name. Friendship requires an invite. Maximum 200 friends [Assumption].

**Acceptance criteria**
- Before consent, nothing is sent except the Sign in with Apple exchange; checked with a network log.
- Turning sharing off or deleting the account removes the server data within 24 hours, and the account can be deleted inside the app [Unverified: Apple requires in-app account deletion for apps that create accounts; from memory].
- A street-level upload contains no edge within the home zone; unit-tested on the device.
- Feed items carry a date only, and appear at the next daily batch at the earliest.
- Block and report are available on every friend and feed item.

### Backlog after these (in priority order)

| # | Feature | Rationale |
|---|---|---|
| 1 | Friends (F6), if not in v1 | Growth loop. Option B puts it in v1.1. |
| 2 | Club groups (a shared leaderboard for a run club) | Clubs meet in person [Research]. A natural extension of Friends. |
| 3 | Apple Watch route hand-off or a Watch app | Following on the wrist is better than on the phone. Feasibility is unverified (section 6.8). |
| 4 | Offline photo bundle per city | Removes per-photo network requests (a privacy and offline gain). |
| 5 | GPX/FIT import and a Strava/Garmin bridge | Runners whose routes never reach Health. Strava's API rules limit showing its data to others [Research]. |
| 6 | Yearly recap | December sharing moment. |
| 7 | Turn-by-turn audio cues | Needs background location. Only if runners ask for it. |
| 8 | Cycling mode | Different audience; same engine. |

---

## 3. Screen inventory

**Navigation (changed).** Floating iOS 26 tab bar.
- **v1:** **Map · Discover · Runs**
- **v1.1:** **Map · Discover · Friends · Runs**
- **Neighborhoods moved into the Map tab.** The bottom sheet's "Neighborhoods" row (and swiping the sheet up) opens the neighborhood list. Discover needed a tab more, because it is used before a run.
- Settings opens from the profile button on Map. Cities opens from the city name.

| # | Screen | Release | Purpose | Key elements | Empty / loading / error |
|---|---|---|---|---|---|
| S01 | Welcome | v1 | The promise | Hero map; "See where you've run. Run somewhere new."; three promises; Get started | — |
| S02 | Apple Health explainer | v1 | Before the Health sheet | Reads workouts and routes only; routes stay on the phone | "Not now" leads to a connect card on Map |
| S03 | Importing your history | v1 | Progress plus a filling map | Progress, streets so far, steps | Pack download; no workouts found; city not supported; offline |
| S04 | Map (home), light and dark | v1 | Core view | Map; covered, uncovered, new and path line styles; sheet with 8.4%, Neighborhoods row, last run; "Plan a run" | Updating capsule; empty city; pack update available |
| S05 | Neighborhoods (from the Map sheet) | v1 | City-wide progress | Search, sort, rows with bars; "Paths & trails" section | No runs yet; no neighborhood data |
| S06 | Neighborhood detail | v1 | One neighborhood | Map, %, miles, streets, lists; Plus gate on full lists; "Run here" opens Discover | Not run yet |
| S07 | Street sheet and report | v1 | Detail and disputes | Coverage strip; Report menu | Marked-by-you confirmation |
| S08 | Runs | v1 | Processed workouts | Grouped list, "+9 streets", "Followed a Discover route" tag | No route; outside cities; matching |
| S09 | Post-run summary | v1 | What a run added | Stat tiles, before→after bars, new streets | Zero new; still matching |
| S10 | Share card | v1 | Make an image | Preview, scope, format, style | Render error |
| S11 | Paywall (StreetFill Plus) | v1 | In-context upsell | Context hero; v1 benefits only; $29.99/year; trial; restore | StoreKit loading or error; already Plus |
| S12 | Cities | v1 | Home, found, add | Teaser percentages for cities in history | Not available yet; downloading |
| S13 | Settings and data sources | v1 | Trust and control | Health status; counting; location ("only when you ask"); street-level previews toggle; map data; iCloud; export; delete | Health disconnected; re-matching |
| S14 | Lock Screen notification | v1 | Post-run trigger | "9 new streets…" | — |
| S15 | Home Screen widget | v1 | Ambient progress | Small and medium | No data |
| **S16** | Discover (controls) | v1 | Set up a run | Start point card; length; loop or out-and-back; terrain slider; New-to-me slider; scenery chips; quiet streets; "Find runs" | No pack: "Download Chicago first". Start outside the city: "Pick a start inside Chicago". Free limit reached: paywall |
| **S17** | Route options | v1 | Pick one of three | Three cards: mini-map, distance, gain, % new, new neighborhoods, highlight thumbnails | Generating (skeleton cards, under 2 s); "Only 2 distinct routes here"; preference cannot be met (labelled) |
| **S18** | Route detail | v1 | Decide and start | Map, new parts styled differently, elevation profile with markers, highlight photo strip, new streets, Start, Save | Images loading (placeholders); no highlights ("No named highlights on this route") |
| **S19** | Highlight card | v1 | What you'll see | Photo with attribution; category; description; position on route; Street view; Add to Want to run | No photo: illustrated placeholder; no Look Around: button hidden |
| **S20** | Start route sheet | v1 | How to follow | "Follow in StreetFill" (map with your position, When-In-Use); "Export GPX"; note that credit comes from the recorded workout | Location denied: map without a dot, plus a Settings link |
| **S21** | Sign in for Friends | v1.1 | Accounts plus consent | Explanation; what is shared and never shared; consent toggle; Sign in with Apple | Sign-in failed; under the age gate: "Friends isn't available for your age range" |
| **S22** | Friends home | v1.1 | Feed and leaderboard | Feed with cheers; Leaderboard with scope and metric | No friends: an invite prompt; no activity yet |
| **S23** | Compare with a friend | v1.1 | Only you / Both / Only them | Venn counts; neighborhood rows; "Run there next" | The friend shares nothing at street level: map hidden, counts only |
| **S24** | Invite a friend | v1.1 | Grow | Link, code, QR, share button; pending invites | Expired link |
| **S25** | Sharing & privacy | v1.1 | Control what friends see | Toggles; home zone map and radius; hidden neighborhoods; feed delay; never-shared list; delete account | — |

The v1.1 concept screens C1 and C2 from revision 1 are replaced by S16–S18 and S22.

---

## 4. User flows

**4.1 First launch to first map (v1).** S01 → S02 → Health sheet → confirm city → S03 → S04, with a one-time tip on "Plan a run" → notification permission prompt after the first map.

**4.2 Planning a run (v1)**
1. Discover tab (S16), or "Run here" on S06, or "Run there next" on S23. The start point and scope are prefilled.
2. Set length, terrain, New to me and scenery → **Find runs**.
3. S17 shows three options → tap one → S18 → tap a highlight → S19 → back.
4. **Start** → S20 → "Follow in StreetFill", or "Export GPX" to a watch or running app.
5. Run, recording with the Watch or a running app as usual.
6. The finished workout is matched (F1). S09 also shows "You ran *Lakefront to Montrose Beach*: 14 new streets", and the route moves from Want to run to Been.

**4.3 After a run (v1).** Background match → S14 → S09 → S10. Unchanged.

**4.4 Sharing (v1).** Unchanged.

**4.5 Upgrading (v1).** Paywall entry points:
- a fourth route generation in a week (S16)
- Discover in a locked city
- a locked city (S12)
- "See all streets left" (S06)
- the Plus row in Settings

S11 → StoreKit → unlock in place.

**4.6 Adding a second city (v1).** S04 city name → S12 → locked teaser → S11 or download → match history.

**4.7 Adding a friend (v1.1)**
1. Friends tab → S21 sign-in and consent (first time) → S24.
2. Share the link to a friend → the friend installs → Health import (their map exists on first launch; history solves the empty-map cold start) → the friend accepts → both see S22.

**4.8 Comparing (v1.1).** S22 → tap Priya → S23 → "Only Priya: Edgewater" → "Run there next" → S16 with a start in Edgewater.

---

## 5. Street-matching design

Unchanged from revision 1 except for 5.2. Thresholds are **[Tune]** for the week-one spike.

### 5.1 Data source
- OpenStreetMap regional extracts; packs rebuilt monthly.
- **Licence.** The ODbL applies. Packs are derivative databases offered under the ODbL. Displays and images credit "© OpenStreetMap contributors" [Unverified; week-one check].

### 5.2 Which ways count (revised)
The pack now holds **two layers**:
- **Streets, which count toward the street percentage.** As before:
  - included `highway` = `primary`, `secondary`, `tertiary`, `unclassified`, `residential`, `living_street`, `pedestrian`; `trunk` where foot is allowed
  - excluded: motorways, ramps, `service` (alleys, driveways), anything private or `foot=no`, construction, tunnels and lower-level roads
- **Paths and trails, which count toward "Paths & trails" and are routable.** New:
  - `footway` (not `footway=sidewalk` or `crossing`), `path`, `cycleway` where foot is allowed, `track`, `bridleway` where foot is allowed
  - `steps`: routable only, with a cost penalty
  - Named paths become trails with their own percentage (for example "Lakefront Trail"). Unnamed paths add to miles only.
  - Sidewalks mapped separately stay out of both layers, because a run along a sidewalk is credited to its street through the distance tolerance.
- **Revised decision on paths.** In revision 1 paths did not count at all. Beach and lakefront paths are exactly what the owner wants to run, so they now count, in their own figure. The street percentage stays streets-only (decision D7).
- **Routing graph.** The routable graph = streets + paths + short crossing connectors.

### 5.3 Pack format
- SQLite, gzip-compressed, with a hash and a `manifest.json`. Tables: `meta`, `neighborhoods`, `streets`, `edges`, `grid`, plus the new tables in section 6.6.
- Checkpoints are generated from geometry at a fixed spacing, identically in Python and Swift.

### 5.4 Matching rule [Tune]
1. **Clean the route.** Drop locations with accuracy above 25 m. Drop points implying speed above 7 m/s. Split at gaps longer than 30 s and 100 m. Densify to one point per 5 m.
2. **Checkpoints.** Every 15 m along an edge. None within 10 m of an intersection. One midpoint on edges shorter than 30 m.
3. **Visit test.** A visited checkpoint has a route point within 20 m and a bearing within 30°. The limit widens by road class: primary +8 m, secondary +5 m. Paths use 15 m with no widening, because paths often run close to and parallel with streets.
4. **Ambiguity.** Credit the nearer edge. Within 3 m of a tie, credit neither.
   - **New:** a path running alongside a street within 25 m (lakefront paths beside a drive) gets the credit when the route matches the path's geometry better over 100 m. This is a known hard case, measured separately in the spike.
5. **Coverage.** Coverage = visited checkpoints ÷ checkpoints. Complete at 90%. Percentage = covered length ÷ total length.
6. **Storage and port.** Visited checkpoints are stored per workout, so deletions are exact. The matcher is written in Python first, then ported to Swift with shared fixtures; the two must agree on 99.5% or more of checkpoints.
7. **Fallback.** An HMM map-matcher if the spike falls short.

### 5.5 Edge cases
Handled as in revision 1:
- GPS drift
- parallel streets and alleys
- wide arterials
- divided boulevards
- bridges
- tunnels
- private roads
- map errors
- out-and-backs
- stops
- pack updates: re-match all workouts from Health in the background
- indoor runs

New: paths beside streets (5.4 step 4), and beaches. Sand areas are polygons, not ways, so a beach highlight counts as "visited" when the route passes within 50 m [Tune]; it never counts toward percentages.

### 5.6 City and neighborhood boundaries
- **City:** the OSM municipal boundary (`admin_level=8` for most US cities [Unverified per city]), with per-city config overrides.
- **Neighborhoods, in order:** official open data where the licence allows (Chicago's 77 community areas [Unverified licence]) → OSM neighborhood boundaries → approximate regions around OSM place points → none.

### 5.7 Pipeline validation
- Length or count change above 3% versus the last version blocks publishing.
- Neighborhoods sum to the city total.
- A visual check on each city's first publish.

### 5.8 Accuracy measurement
About 150 hand-labelled street segments. Agreement and recall both 95% or higher [Research]. Add 20 path segments, reported separately.

### 5.9 Disputes
Unchanged:
- I ran this (marked-by-you style)
- I didn't run this
- Not a public street
- Wrong on the map (anonymous report: OSM way id and reason only)

---

## 6. Route-generation and highlights design (new)

All weights and thresholds are **[Tune]** for the week-3 route spike.

### 6.1 Graph on the phone
- **Nodes:** intersections and way ends from the routing graph (5.2). Elevation per node.
- **Edges:** both directions; one-way restrictions are ignored on foot unless `foot=no`.
- **Edge fields:**
  - length, road class, path flag
  - rise and fall in each direction
  - a short elevation profile
  - scenery flags (water, beach, park, landmark nearby)
  - neighborhood id
- **Personal state, joined on the device only:** the user's coverage per edge from `EdgeProgress`. Because newness is personal, routing must run on the phone. That suits the privacy stance.

### 6.2 Edge cost
For each edge direction:

```
cost(e) = length(e) × max(0.15, 1 + T(e) + Q(e) + R(e) − N(e) − V(e))
```

| Term | Preference | Starting rule |
|---|---|---|
| **T**, terrain | Flat · Rolling · Hilly slider, s from −1 to +1 | grade g = |rise| ÷ length, in %. **Flat** (s < 0): `+0.25·|s|·max(0, g − 1.5)`. **Hilly** (s > 0): `−0.5·s·min(g, 8)/8`. **Rolling**: 0. |
| **Q**, quiet | Quiet streets toggle; also a mild default | Quiet on: primary/trunk +0.6, secondary +0.3. Always: steps +1.0, primary +0.15. |
| **R**, reuse | Loop shape | +2.0 if the edge is already in this route (any direction). Out-and-back allows the return leg. |
| **N**, newness | New-to-me slider, n from 0 to 1 | `0.8·n·(1 − cov(e)) − 0.2·n·cov(e)`, where cov(e) is the user's coverage of that edge |
| **V**, scenery | Chips | +0.5 for each selected flag present on the edge, capped at 0.8 |

### 6.3 Candidate generation (loop)
1. **Snap the start** to the nearest routable node within 150 m.
2. **Radius.** For a target distance D: `r = 1.1 · D / (2π)`.
3. **Waypoints.** For each of K = 24 bearings θ (evenly spaced plus jitter), place waypoint W1 at distance r on bearing θ and W2 at bearing θ + 60° (±15° jitter).
4. **Snap waypoints to rewarding nodes.** Snap each waypoint to the highest-reward node within 200 m, where reward = new edges nearby + selected scenery + highlights.
5. **Scenery pull.** If Waterfront is selected and a water-flagged edge lies within D/2, one waypoint in that sector moves onto it. The same applies to Parks and Landmarks, using the nearest qualifying highlight.
6. **Path.** A* for S → W1 → W2 → S, with the reuse penalty applied to later legs. The heuristic is straight-line distance × 0.15, which stays admissible because 0.15 is the minimum multiplier.
7. **Distance fit.** If the length misses D by more than 5%, scale r by D ÷ length and retry, up to 3 times.
8. **Out-and-back.** One waypoint at D/2; the return either reuses the outbound path or takes a parallel street (penalty 1.0).

### 6.4 Scoring and choosing three
```
score = 3·|len − D|/D + 2·|newShare − n| + 1.5·terrainMiss
        − 1·sceneryShare − 0.3·min(highlights, 3)
        + 2·repeatedShare + 0.05·max(0, turnsPerMile − 8) + 1·deadEndSpurs
```
- `terrainMiss` = distance outside the target band for gain per mile. Bands: flat 15 ft/mi or less, rolling 15–50, hilly 50 or more.
- Choose the best-scoring route. Then choose the next best whose overlap by length with every chosen route is under 40%, until there are three.

### 6.5 Annotation, performance, reference
- **Annotation:**
  - distance
  - elevation gain (summed from edge profiles, after smoothing)
  - new share (the share of length on edges with coverage below 50%)
  - new neighborhoods touched (ones where the user's coverage is 0%)
  - expected percentage gain per neighborhood
  - highlights in route order with the mile point
- **Performance targets** (iPhone 13):
  - three options for 5 mi in 2 s or less, and 13 mi in 4 s or less
  - peak memory 60 MB or less
  - search limited to the subgraph within D/2 + 0.5 mi of the start
- **Python reference first.** The same cost and scoring code runs in the pipeline repository against real packs and the owner's real coverage. It produces fixtures (start, preferences, seed → edge list). The Swift port must reproduce at least 95% of each route's length on the same seed; floating-point ties make exact equality unrealistic.
- **Safety rules, which are not preferences:**
  - Never use excluded ways.
  - Cross primary roads only at graph nodes, which are intersections.
  - Show a one-line note on S20: "Routes are generated from map data. Use your judgement about traffic and safety."

### 6.6 What the packs now need, and the size impact

| Addition | Source | Notes |
|---|---|---|
| Routable topology (node ids, adjacency) and the path layer | OpenStreetMap | Section 5.2 |
| Elevation per node and a profile per edge (one sample per 30 m, stored as whole decimetres) | US: USGS 3DEP 1/3 arc-second DEM [Unverified: public domain]. Elsewhere: Copernicus GLO-30 [Unverified licence]. | Bridges and tunnels are interpolated between their end nodes, because the elevation model shows the water or ground below. Light smoothing removes noise. |
| Scenery flags per edge | OSM: water within 100 m (coastline, riverbank, water polygons); beach within 150 m; park within 50 m; highlight within 75 m [Tune] | Bit flags |
| Highlights table | OSM features: `natural=beach`; `tourism=attraction`, `viewpoint`, `artwork`, `museum`; `historic=*`; named `leisure=park` over 1 ha; `man_made=lighthouse`, `pier`; named bridges; named fountains | Fields: id, name, category, point, Wikidata id, description, photo URL, author, licence. Top 2,000 per city by a score (has a Wikidata id, has a photo, size). |

**Size estimate [Assumption, measure in week 2]**
- Paths add about 20–40% more edges. Topology adds about 10%. Elevation profiles add about 15–25%.
- Scenery flags are negligible. Highlights are under 0.5 MB.
- **A large city goes from about 2–6 MB to about 4–10 MB compressed.**
- Photos are not in the pack. They are fetched from the CDN on demand, at about 30 KB per thumbnail [Assumption].

### 6.7 Images: sources, licensing, privacy
- **Freely licensed photos.**
  - The pipeline resolves each highlight's Wikidata image or Commons file and reads the licence and author through the Commons API.
  - It keeps only public-domain, CC0, CC BY and CC BY-SA images, makes a 480 px thumbnail, and mirrors it to the StreetFill CDN with the attribution stored in the pack.
  - [Unverified: that resizing and mirroring with attribution meets CC BY-SA terms, and Wikimedia's policy on bulk reuse. Check both in week 1.]
- **Look Around.**
  - On S18 and S19 the app requests a Look Around scene at the highlight's coordinate and makes a static image with `MKLookAroundSnapshotter` (iOS 16.0+). Apple's page lists no usage limits [Research 2026-11-15].
  - Coverage by city is **not verified**; check Chicago in week 1.
  - Whether snapshots may be cached, and for how long, under the MapKit terms: [Unverified].
  - "Street view" opens the interactive Look Around viewer [Unverified: exact SwiftUI API].
- **Fallback.** An illustrated category placeholder and the name. The mockups use only such illustrations, labelled as placeholders for real photos.
- **Privacy effect.**
  - Photo requests go to StreetFill's CDN and reveal which highlight thumbnails an IP address fetched. Keep CDN logs minimal.
  - Look Around requests send highlight coordinates to Apple. These are not the route, but a run of nearby coordinates hints at the planned area.
  - Mitigations: fetch only on S18 and S19, never prefetch for unviewed options, and offer the Settings toggle "Street-level previews (Apple Look Around)". Disclose both in the privacy policy.
  - Backlog item 4 (offline photo bundles) removes per-photo requests.

### 6.8 Following a route

| Option | Location permission | Verdict |
|---|---|---|
| **Pick start on the map**, or choose one of my usual starts | None. Usual starts come from the user's own workout start points, on the device. | **Default in v1** |
| **"Use my location"** for the start | When-In-Use, asked on first tap only | **In v1, optional** |
| **Follow in StreetFill**: the route on a map with your position, while the app is open | When-In-Use; foreground only; no background updates; no turn-by-turn | **In v1** |
| **Export GPX** through the share sheet, to watch and running apps that import routes | None | **In v1** |
| Hand-off to Apple Maps | None | **Not recommended.** I believe Maps cannot take an arbitrary route geometry and would plan its own route, losing the new streets [Unverified]. |
| Send to Apple Watch | — | **Unverified.** Whether a third-party iPhone app can send a route for the Watch Workout app to follow, for example through WorkoutKit, is not confirmed. Check in week 1. Otherwise, a Watch app is backlog. |

**Recommendation for v1:** pick the start on the map (with "Use my location" optional), "Follow in StreetFill" with a position dot while the app is open, and GPX export. Credit still comes **only from the recorded workout** in Health, so following never reintroduces the live-tracking failures that hurt rivals. Location never leaves the device.

---

## 7. Data model

**Principle.** Apple Health is the source of truth. Computed coverage is a rebuildable cache, which keeps health-derived data out of iCloud (guideline 5.1.3 [Research]).

**SwiftData entities. Local store, no sync:**
- `WorkoutRecord`: as in revision 1, plus `followedRouteId` (optional)
- `WorkoutCoverage`
- `EdgeProgress`
- `StreetProgress`
- `AreaProgress`: now also covers trails, with `kind` = city / neighborhood / trail
- `CityPack`
- `RouteRequestLog`: local only, for the free-tier weekly count

**CloudKit (private database), separate store.** Planned routes are user content, not health data, so they may sync:
- `Correction`
- `UserPreference`: adds Discover defaults (length, terrain, newness, scenery, quiet), location-feature toggles, and Look Around on or off
- `SavedRoute`: `id`, `cityId`, `name`, `edgeIds` (compressed), `startNodeId`, `distanceM`, `gainM`, `newShareAtCreation`, `preferences`, `createdAt`, `status` (wantToRun / run), `runWorkoutUUID`. That last field is a local link and is never uploaded to a server.
- `SavedPlace`: Want-to-run neighborhoods and highlights

**Caches (files):**
- highlight thumbnails and Look Around snapshots, in Caches, purgeable
- the App Group widget summary

**Friends (v1.1). Server, Postgres:**

| Table | Fields |
|---|---|
| `profiles` | `user_id` (from Sign in with Apple), `display_name`, `avatar_emoji`, `created_at`, `age_ok` (boolean) |
| `friendships` | `user_a`, `user_b`, `created_at`; one row per pair |
| `invites` | `code`, `inviter_id`, `expires_at`, `uses_left` |
| `area_summaries` | `user_id`, `city_id`, `area_kind`, `area_id`, `pct` (one decimal), `streets_complete`, `first_reached_month`, `updated_on` (date) |
| `weekly_counts` | `user_id`, `city_id`, `week_start`, `new_streets`, `new_areas` |
| `feed_events` | `id`, `user_id`, `kind` (new_area / milestone / trail_complete), `city_id`, `area_id`, `value`, `posted_on` (date) |
| `street_shares` (opt-in) | `user_id`, `city_id`, `pack_version`, `edge_bitmap` (home zone already removed) |
| `shared_items` (opt-in) | `user_id`, `kind` (route / place), `payload`. A route payload is edge ids with the first and last 0.1 mi trimmed [Assumption]. |
| `cheers`, `blocks`, `reports` | standard |

Row-level rules: a user reads another user's rows only if a friendship exists and no block exists.

**On the device for Friends:** a local `FriendCache` store, rebuilt from the server. The home zone center and radius stay **on the device only**; the server never learns them.

---

## 8. Architecture

### 8.1 On the phone

| Module | Responsibility |
|---|---|
| `StreetCore` | Pack reader, checkpoints, route cleaning, matcher, coverage. Pure Swift. |
| `RouteCore` (new, same package) | Graph loader, edge cost, A*, candidate generation, scoring, annotation. Pure Swift, fixture-tested against Python. |
| `HealthSync` | Authorization, anchored query, routes, background delivery, deletions, duplicates, saved-route match detection. |
| `PackService` | Manifest, city detection, downloads, versions, re-match. |
| `ProgressStore` | SwiftData containers: local and CloudKit. |
| `MapUI` | Overlays for covered, uncovered, new, paths and routes. |
| `Highlights` (new) | Highlight lookup, CDN image loader with cache, Look Around snapshotter, placeholders, elevation-profile view. |
| `FollowUI` (new) | Follow-along map with a When-In-Use position dot; GPX writer. |
| `Features` | SwiftUI screens. |
| `ShareCard` | Share image rendering. |
| `Store` | StoreKit 2 subscriptions. |
| `Notify` | Local notifications. |
| `WidgetExtension` | Widgets. |
| `Analytics` | Event wrapper. |
| `Social` (new, v1.1) | Sign in with Apple, API client, consent, daily summary upload, home-zone filter, feed, compare. Not present in the v1 binary. |

Risks carried over (Unverified, as in revision 1): map rendering performance (fallback: `MKMapView` with batched overlays) and reading HealthKit while the phone is locked.

### 8.2 Python pipeline
1. OSM extract.
2. Filter streets and paths.
3. Clip; split at neighborhoods; pair carriageways.
4. Build topology.
5. Sample the elevation model (3DEP) per node and per edge; interpolate bridges.
6. Compute scenery flags.
7. Extract and score highlights; resolve photos and licences; make and mirror thumbnails.
8. Write SQLite; validate; publish to S3-compatible storage behind a CDN with `manifest.json`.

The **reference matcher, reference route generator** and the fixture generators live in the same repository. PostGIS is optional [Assumption].

### 8.3 Friends backend (v1.1)
- **Recommendation: Supabase.** Managed Postgres, Sign in with Apple through its Auth, row-level security for the friends-only rule, and one or two Edge Functions (invite redemption, daily feed batching).
- The schema stays plain Postgres, so moving to FastAPI on a small host later is straightforward.
- **Alternative:** FastAPI + Postgres from day one (the owner's home ground), at the cost of running and securing a server.
- **No push notifications** in the first Friends release. The feed refreshes on app open and through background app refresh. Revisit once there is usage.

### 8.4 Deliberately not built
- No server-side matching or routing, and no route upload.
- No background location, no turn-by-turn.
- No public profiles, search, comments or chat.
- No AI.
- No unreleased feature hidden in a shipped binary. Guideline 2.5.19 forbids dormant features [Research], so the Social module ships only when Friends ships.

---

## 9. Privacy and App Store review notes

**HealthKit**
- Read only: workouts and workout routes. Purpose string (`NSHealthShareUsageDescription`): "StreetFill reads your workouts and their routes to find the streets you've run or walked. Your routes stay on this iPhone."
- Entitlements: HealthKit, and Background Delivery [Apple docs].
- HealthKit does not reveal whether read access was denied [Unverified], hence the S03 empty state.

**Location (changed)**
- When-In-Use only, requested on first tap of "Use my location" or "Follow in StreetFill". Never Always, never background.
- Purpose string (`NSLocationWhenInUseUsageDescription`): "StreetFill uses your location only when you ask: to start a route where you are, or to show your position on a route. It never leaves your iPhone."
- Location is not stored. Matched coverage still comes only from Health.

**Health-data rules** (5.1.3 as summarised in the research: no health data for advertising; no personal health information in iCloud [Research])
- Coverage is not synced through CloudKit. Saved routes are planned content and do sync.
- **Friends (v1.1).** Area summaries derived from Health workouts go to the StreetFill server and to friends. This needs an explicit, separate consent before the first upload (S21), withdrawable at any time with server deletion.
  - 5.1.2(i) requires clear disclosure and explicit permission before sharing personal data with third parties [Research].
  - [Unverified: the exact 5.1.3 text on storing HealthKit-derived data on a developer's own server. Re-read the guideline before the v1.1 submission.]
- No health-derived data is used for marketing or analytics in production (section 11).

**Images.** Requests to the CDN and to Apple Look Around are disclosed (6.7). Photo attribution is shown wherever a photo appears.

**Social and age (v1.1)** [Research for the rules; recommendations are mine]
- **Age rating.** The questionnaire's social-media capability question (required since September 2026) implies a minimum 13+ rating. The new **Shared Location** declaration (opens Nov 16, 2026, due Jan 12, 2027) should be answered "yes" for the Friends release, because area-level location is shared with friends. A v1 without Friends answers "no".
- **Age-verification laws.** Texas SB 2420 is in effect; California AB 1043 starts Jan 1, 2027. Use Apple's Declared Age Range API. **Recommendation:** Friends is available only to users in an adult age range at first (decision D17). The rest of the app is unaffected.
- **Guideline 1.2 (user-generated content).** Display names and feed items count as content, so the app needs filtering of display names, report and block on every friend and feed item, and published contact information. Avoiding comments keeps this small.
- **Account deletion** inside the app [Unverified, from memory].

**Other guidelines** [Research]
- **2.5.19:** no dormant features.
- **3.1.2(a):** the paywall lists only shipped features.
- **2.5.2:** packs are data, not code.
- **1.4.1:** no health claims.
- **5.1.1(ix):** fitness and maps, not a health service; an individual account is likely fine [Assumption].
- **Foldable "iPhone Duo":** screenshots mandatory from April 2027.
- **SDK:** iOS 26 SDK now; iOS 27 SDK from April 2027.

**Privacy label (expected)**
- **v1:**
  - Usage Data and Diagnostics: not linked to identity
  - Location: not collected; it stays on the device
  - Health & Fitness: not collected
- **v1.1 adds, linked to the account, for app functionality:**
  - Health & Fitness (area summaries)
  - Coarse Location (neighborhood level)
  - Contact Info (name from Sign in with Apple, if provided)
  - User ID

---

## 10. Monetization

Price hypothesis unchanged: **StreetFill Plus at $29.99/year** [Research], with a 7-day trial [Assumption]. Comparable products: CityStrides $50/year, Wandrer $40/year, Fog of World $30 paid [Research]. Route generators with preferences exist for free (Trail Router, RunCulture, Roovr), and Strava keeps its route builder filters in its subscription [Research 2026-11-15]. So the paid part of Discover must be the personal "new to you" value and volume, not the controls themselves.

| | Free | Plus |
|---|---|---|
| History import, home-city map, all neighborhood and trail percentages | ✓ | ✓ |
| Post-run summary, notification, widget, share cards | ✓ | ✓ |
| Disputes, export, delete | ✓ | ✓ |
| **Discover in the home city, all preferences, highlights with photos, follow and GPX** | **3 generations per week** (each gives up to 3 options) | **Unlimited** |
| Discover in other cities, including when travelling | — | ✓ |
| Want to run list | 5 saved items | Unlimited |
| Full "streets left" lists | First 3 per list | All |
| Other cities (maps, neighborhoods) | Teaser percentage | Unlimited |
| **Friends (v1.1): compare, leaderboards, feed, invites** | **✓ always free** (drives growth) | ✓ |

**Paywall entry points (in context only):**
- the fourth generation in a week
- Discover in a locked city
- a locked city
- "See all streets left"
- saving a sixth Want to run item
- Settings

Never during onboarding or before the first map. The paywall never lists unshipped features.

**Never paywalled:**
- history
- home map and percentages
- post-run summary
- share cards
- corrections, export, deletion
- following a route already generated
- everything in Friends

Discover gives a non-travelling runner a real reason to pay in v1, which answers revision 1's main monetization weakness. Base rate to keep in mind: a median new subscription app earns about $72 a month after a year [Research].

---

## 11. Analytics

Rules:
- No coordinates, street names, workout dates or distances in production events.
- Buckets only, and only in TestFlight (D11).
- A privacy-focused SDK [Research] behind one wrapper.
- 12 events; the first 10 are the core.

| # | Event | Properties | Question it answers |
|---|---|---|---|
| 1 | `onboarding_step` | step, result | Where do people drop out before the first map? |
| 2 | `history_import_finished` | duration, workout, route-share buckets; sources | Does history-on-first-launch work? How many lack routes? |
| 3 | `session_after_new_run` | — | Retention gate (gate 3) |
| 4 | `route_generated` | terrain, newness and scenery buckets; length bucket; options returned; time bucket | Is Discover used, how, and is it fast enough? |
| 5 | `route_option_opened` / `route_saved` | option rank, highlight count bucket, had photo | Do highlights and photos drive choice? |
| 6 | `route_started` | method (follow / gpx); location permission granted | Which way of following do runners use? |
| 7 | `route_run_detected` | overlap bucket | Do generated routes get run? (gate 3 Discover measure) |
| 8 | `share_completed` | scope, format | Unprompted sharing (gate 3) |
| 9 | `paywall_viewed` / `purchase_completed` | entry point, trial | Which entry point converts? |
| 10 | `correction_submitted` | kind | Live matching-quality signal |
| 11 | `friend_invite_sent` / `friend_added` (v1.1) | channel | Does the growth loop work? |
| 12 | `compare_viewed` / `leaderboard_viewed` (v1.1) | scope | Is competition the reason people come back? |

---

## 12. Phasing and milestone plan

The owner's brief asked for an MVP in 4–8 weeks. Discover makes v1 bigger. I estimate it adds **3–4 weeks** of nights-and-weekends work:
- pack upgrades (paths, elevation, scenery, highlights, photos)
- a Python reference generator and a route-quality spike
- the Swift port
- four screens plus the follow-along map

Friends adds about **6–7 weeks**:
- accounts and backend
- consent, privacy and home-zone logic
- feed and leaderboards
- moderation basics
- review and age-rating work

These are estimates [Assumption], and they are on the optimistic side for a first iOS app.

### Option A: v1 as planned (8 weeks), then Discover, then Friends
- v1 (matching, progress, share, paywall) in **week 8**.
- Discover v1.1 around **week 13**.
- Friends v1.2 around **week 20**.
- **For:** meets the 8-week brief, and real-market feedback four weeks sooner.
- **Against:** v1 has a weak reason to pay and no reason to open the app *before* a run. It launches as "a map", which free rivals already offer.

### Option B (recommended): v1 includes Discover (about 12 weeks), Friends next (about week 19)
- **For:**
  - Route suggestions are the main reason to pay (revision 1, section 9), so B launches with them.
  - Discover adds a pre-run habit on top of the post-run one.
  - The positioning is distinct at launch: no rival generator uses the runner's own history [Research 2026-11-15].
- **Against:** v1 is about 4 weeks later than the brief, and more surface area means more risk for a first iOS app.

**I agree with your lean toward B, with two conditions:**
1. **A route-quality gate in week 3 decides it.** If generated routes are not good (gate 2), fall back to Option A at that point: ship v1 without Discover in week 8–9 and keep working on Discover for v1.1. Little is wasted, because the pack work is needed either way.
2. **Keep v1 Discover narrow.** If behind, cut in this order:
   1. mirrored Commons photos (Look Around and placeholders only)
   2. time-based length
   3. out-and-back
   4. follow-along map (GPX only)
   5. third metro

One point I would add in Friends' favour: because history-on-first-launch gives a new friend a full map on day one, Friends avoids the usual empty-network problem better than most social features. That is a reason to start it **immediately** after v1, not to push it later.

### Option B milestone plan (recommended)

| Week | Work | Exit criterion |
|---|---|---|
| 1 | **Matching spike** (Python, own Health export, about 150 + 20 labelled segments).<br>**Week-1 checks:** OSM licence; Garmin and Strava routes in Health; name availability and trademark (D1); Look Around coverage in Chicago; 3DEP and Commons licence terms; Watch route hand-off feasibility; HealthKit locked-device behavior. | **Gate 1** passed (95% or more). A one-page note answers each check. |
| 2 | **Pipeline v2:** streets + paths, topology, elevation, scenery, highlights, photo resolution and mirroring; packs for the launch metro and two others. | Packs pass validation. Largest is 10 MB or less compressed [Tune]. 80% or more of the top 100 Chicago highlights have a photo or a Look Around scene [Tune]. |
| 3 | **Route spike:** Python reference generator on real packs and the owner's coverage; fixtures. | **Gate 2** passed (section 14). |
| 4 | **iOS foundations:** skeleton, map rendering prototype (day 1), HealthKit import, Swift matcher port, SwiftData. | Swift matches Python on 99.5% or more of checkpoints. 1,000 workouts in 60 s or less. |
| 5 | **Progress UI:** S04 (light and dark), Neighborhoods in the Map sheet (S05), S06, S07; city detection. | City percentage matches the reference within 0.1. Map pans smoothly. |
| 6 | **After the run:** background delivery, S08, S09, S14, S15.<br>**TestFlight to the first 10 runners** (no Discover yet). | 5 of 5 runs notify correctly. The build passes TestFlight review. |
| 7 | **RouteCore** Swift port; S16 and S17. | Swift reproduces 95% or more of fixture route length. Three options for 5 mi in 2 s or less on an iPhone 13. |
| 8 | **S18–S20:** highlights, photos, Look Around, elevation profile, follow-along map, GPX export, saved routes and Been detection.<br>**TestFlight to 30 runners, with Discover.** | A generated route can be followed and exported, and once run it is detected as run. 30 testers installed. |
| 9 | S10 share, onboarding S01–S03, S11 paywall (with Discover limits), S12, S13. | Sandbox purchase, restore and trial work. Every state in section 3 can be reached. |
| 10 | Fix from testers (matching, routes), performance, accessibility (VoiceOver summaries of routes and maps, Dynamic Type). | No crash or data-loss bugs. Correction rate below 1 per 10 runs. No "unrunnable route" report left open. |
| 11 | App Store assets, privacy policy and label, submission. | Submitted. |
| 12 | Launch in one metro (own map post, run clubs). Read **Gate 3**. | Approved and launched. Gate 3 decision recorded. |
| 13–19 | **Friends v1.1:** Supabase schema and row-level rules (13); sign-in, consent, age gate (14); summaries upload and home-zone filter (15); invite, S22 and S23 (16–17); S25, block and report, account deletion (18); TestFlight with clubs, submit (19). | **Gate 4** (section 14). |

### Option A milestone plan (for comparison)

| Weeks | Work |
|---|---|
| 1–8 | Revision 1's plan, unchanged, with TestFlight from week 5 and submission in week 8. The pipeline already includes the path layer so trails show in v1. |
| 9–13 | Discover: pack v2 (9), route spike and gate 2 (10), Swift port and S16–S17 (11), S18–S20 (12), TestFlight and submit (13). |
| 14–20 | Friends, as in Option B weeks 13–19. |

---

## 13. Risks and open decisions

**Decisions the owner must make before coding.** My recommendation follows each.

| # | Decision | Recommendation |
|---|---|---|
| D1 | **Final name.** StreetFill is the working name (the owner named the repository StreetFill on 2026-11-15). No app named Streetfill, StreetFill or Lapmap appeared in the top App Store results; this was not a trademark check [Research 2026-11-15]. | Keep **StreetFill**. Run a trademark search (USPTO, class 9 software) and a domain check in week 1. Backups: StreetFill, Lapmap. |
| D2 | **Minimum iOS version.** | **iOS 26.** |
| D3 | **Phasing:** Option A or Option B. | **Option B**, with the week-3 route gate as the switch back to A. |
| D4 | **Free versus Plus.** | Free: everything core plus 3 Discover generations a week. Plus: unlimited Discover, other cities, full street lists. Friends always free. |
| D5 | **iCloud sync scope.** | Corrections, preferences and saved routes only. Coverage is rebuilt from Health. |
| D6 | **Headline metric.** | Percentage of street length; streets complete second. |
| D7 | **Paths and trails** (revised). | Route on them; give named trails their own progress; keep the street percentage streets-only. |
| D8 | **Activity types counted.** | Running, walking, hiking. |
| D9 | **Does "I ran this" count?** | Yes, styled distinctly. It never counts on friends leaderboards. |
| D10 | **Launch metro.** | The owner's own; the mockups use Chicago as an example. |
| D11 | **Analytics.** | Privacy-focused SDK. No health-derived values in production. |
| D12 | **Pack and photo hosting.** | Own S3-compatible storage with a CDN and minimal logs. |
| D13 | **Price and trial.** | $29.99/year, 7-day trial. |
| D14 | **Location permission** (new). | When-In-Use, requested only on tap. Follow-along map plus GPX in v1. No background location. |
| D15 | **Photo sources** (new). | OSM highlights + mirrored freely licensed photos + Look Around + illustrated fallback. If the licence check in week 1 is unclear: Look Around and fallback only. |
| D16 | **Friends backend** (new). | Supabase (Postgres, Sign in with Apple, row-level security). FastAPI only if Supabase limits bite. |
| D17 | **Friends age gate** (new). | Adults only at first, using the Declared Age Range API. Revisit later. |
| D18 | **Street-level sharing with friends** (new). | Off by default; one opt-in covering all friends; home zone 0.25 mi by default. |
| D19 | **Feed timing** (new). | Daily batch, date only, no times. |
| D20 | **Friends leaderboard metrics** (new). | Percentage, and new streets this week or month, by city or neighborhood. Never public. |

**Risks**

| Risk | Mitigation |
|---|---|
| Matching misses or over-credits streets | Gate 1, HMM fallback, disputes, correction rate |
| Generated routes are odd or unsafe (dead ends, busy crossings, closed paths) | Gate 2; quiet-streets default; excluded ways; route reports in S18; safety note |
| Discover is "just another generator"; free ones exist [Research 2026-11-15] | Lead with "new to you", previews and history. Track `route_run_detected`. |
| Timeline slips: 12 weeks is already optimistic | Cut order (section 12); gate 2 fallback to Option A |
| Photo licensing or Look Around terms are stricter than assumed | Week-1 check; the illustrated fallback always works |
| Look Around is thin or missing in some cities [Research 2026-11-15: coverage unverified] | Photos first, fallback art; never depend on it |
| Flat cities make "Hilly" disappointing | Honest labels showing the hilliest option available |
| Social privacy incident, for example inferring a home from coverage | Home zone; area-level default; daily batching; no route upload; hidden neighborhoods |
| App Review for the social release (UGC, age, shared location) | No comments; block and report; age gate; questionnaire answered conservatively |
| Backend cost and operations | Supabase free or low tier [Assumption]; area summaries are tiny |
| Routes never reach Health for some users [Unverified] | Week-1 check; S13 count; import is backlog |
| A rival fixes tracking or adds cities; Strava adds completion [Research] | Speed; history; the Discover and friends combination |
| Small market, modest willingness to pay [Research] | Treat as a modest bet; keep costs near zero |

---

## 14. Validation gates

### Gate 1: matching accuracy (end of week 1). Unchanged.
- **Test:** about 150 hand-labelled street segments plus 20 path segments (reported separately).
- **Pass:** agreement and recall both 95% or higher on streets [Research]. Continue.
- **90–95%:** one extra week with the HMM matcher, then re-measure.
- **Fail:** stop. Use the research fallback: TipLedger, or WheelBook if the owner sells options [Research].

### Gate 2: route quality (end of week 3). New.
- **Test.** The owner generates 20 routes in the home city with the Python reference, spread across settings:
  - terrain: 7 flat, 7 rolling, 6 hilly
  - newness: 30%, 60%, 90%
  - each scenery chip
  - 3, 5 and 10 mi

  Plus 5 routes in a nearby area he knows less well. He rates each 1–5 on "would I run this?"
- **Pass:**
  - 16 or more of the 20 rated 4 or higher
  - no route uses a private, closed or unsafe way, or makes an unmarked crossing of a primary road
  - all within ±5% of the distance
  - new share within ±10 points where feasible
  - the three options per request visibly distinct

  Discover stays in v1 (Option B).
- **Partial (12–15 of 20):** one week of tuning, then re-rate 20 new routes.
- **Fail (under 12, or any unsafe route the cost terms cannot fix):** switch to Option A. Ship v1 without Discover around week 9 and keep developing Discover for v1.1.

### Gate 3: 30-runner TestFlight retention (read at the end of week 11). Revised.
- **Test:** 30 local runners [Research], from week 8; testers' weeks 2 and 3 fall in weeks 9–11.
- **Pass:**
  - 40% or more open the app after three or more separate runs in their weeks 2–3 [Research]
  - **and** 10 or more share a map unprompted [Research]
  - **and** (new) 30% or more run at least one generated route (`route_run_detected`) [Tune]

  Launch publicly and start Friends.
- **Retention passes, Discover usage fails:** keep Discover in the app but stop investing in it. Interview testers about the route quality versus the habit of running set routes.
- **Retention fails:** interview 10 testers. If the cause is matching errors, fix and re-test for two weeks. If indifference, stop investing and use the research fallback [Research].

### Gate 4: Friends beta (end of week 19, v1.1). New.
- **Test:** two run clubs on TestFlight.
- **Pass:** 50% or more of testers who sign in add at least one friend within 7 days, **and** testers with friends show higher weeks 2–3 retention than those without [Tune].
- **Fail:** keep Friends minimal (compare only). Do not build club groups.

### Other stop signal [Research]
Sidewalk launches nationally with fixed tracking before v1 ships. Revisit whether history plus Discover still justifies launching.
