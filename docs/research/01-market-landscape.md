# Deliverable 1: Market landscape (November 2026)

Evidence tags: **[V]** verified on a primary source on 14–15 Nov 2026 (App Store data, App Store review feeds, Apple or vendor pages, retrieved Reddit threads). **[R]** reported by a named secondary source. **[A]** my assumption or inference. All rating counts are US App Store counts.

## 1. The one fact that reshapes everything: supply doubled, demand did not

- New App Store apps: about 600,000 in 2025 (+30%), then about 560,000 in the first half of 2026 alone. Downloads grew 3% in 2025 and 2% in H1 2026. **[R]** Sensor Tower via The New York Times, relayed by [9to5Mac, 20 Jul 2026](https://9to5mac.com/2026/07/20/report-app-store-added-nearly-as-many-new-apps-in-h1-2026-as-in-all-of-2025/).
- New subscription-app launches rose from about 2,000 a month (Jan 2022) to 14,700+ a month (Jan 2026). **[V]** [RevenueCat State of Subscription Apps 2026](https://www.revenuecat.com/state-of-subscription-apps/).
- Base rates from the same report **[V]**: a new subscription app earns a median of about **$72 a month** one year after launch. Within two years, **17.3%** reach $1K monthly recurring revenue and **4.6%** reach $10K. Median download-to-paid conversion is 2.0%.

Our own kill-checks show what that flood looks like inside niches. Every row below is a narrow "tracker for X" idea that sounds underserved:

| Niche idea | Dedicated iOS apps found | Best traction among 2025–26 entrants |
|---|---|---|
| Office-day (return-to-office) tracker | 23 | 12 have zero ratings; best dedicated app has 33 **[V]** |
| Options "wheel" tracker | 7 native, 10+ web | 9 ratings **[V]** |
| Buy-now-pay-later tracker | 4 (all launched Aug–Oct 2026) | 3 ratings combined **[V]** |
| HSA receipt vault | 4 indie + the provider's own app | 6 ratings **[V]** |
| RSU / ESPP tracker | 5 | 4 ratings **[V]** |
| Job alerts for target companies | 3 indie + Simplify's new app | 3 ratings (indie) **[V]** |
| Group availability scheduler | 6 | 17 ratings **[V]** |
| Shift-work sleep planner | 5 | 6 ratings **[V]** |
| Prediction-market tracker | 10+ | 26 ratings **[V]** |
| Congressional / insider trade tracker | 11 new | 3 ratings **[V]** |

**Reading [A]:** building a single-purpose tracker is no longer scarce. Several target communities now treat "I built an app" posts as spam: r/thetagang removed 10 of 11 such posts, r/ADHD removed 6 of 8, and r/Nightshift replies call them "vibe coded" **[V]**. Distribution, hard-to-assemble data, and reliability are the scarce inputs.

## 2. Where 2025–26 breakouts actually came from

Verified rating counts for apps launched in the last 18 months **[V]**:

| App | Launched | Ratings | What explains it |
|---|---|---|---|
| MenuFit (restaurant macros) | Aug 2025 | 54,583 | Mass-market need; 48 of its 50 latest written reviews are 1–3 stars over the paywall |
| StarSnap (sports-card scanner) | Oct 2025 | 29,091 | "Scan and value" collector pattern |
| Bandana (hourly job search) | Mar 2026 | 28,627 | Funded company |
| Stock Analysis | Dec 2025 | 7,772 | Existing web audience |
| Brickify (LEGO scan and value) | Feb 2026 | 6,344 | Scan and value |
| MacroFactor Workouts | Jan 2026 | 4,969 | Incumbent extending to a second app |
| Pin Trading (Disney pins) | Feb 2026 | 1,818 | Scan and value |
| **Sidewalk (walk every block, NYC only)** | May 2026 | 1,033 | One city, free, founder with a prior app |
| Bias Room (K-pop photocards) | May 2026 | 889 | Replaced an abandoned incumbent |
| P&L Calendar (trading journal) | Sep 2025 | 739 | Simple native tool where web incumbents cost $30–99/month **[R]** |

Four patterns recur: an existing audience, a collector "scan and value" land grab, replacement of a failed incumbent, and paid creators.

### How organic growth worked in the case studies (full notes: `research-notes/12-viral-growth-case-studies.md`)

Three mechanisms are routinely confused:

| Mechanism | Test | Examples | What it buys |
|---|---|---|---|
| **Shareability** | Someone posts a result; nobody needs the app to enjoy it | Flighty Passport, Letterboxd, Liftoff rank cards, Spotify Wrapped | Awareness only |
| **Virality** | Normal use requires bringing in another person | GymRats, Partiful, Splitwise, POV event camera, Locket, Candle | Installs as a by-product of use |
| **Network effect** | More users make it better for each user | Strava segments, Beli lists, Ravelry | Retention and defensibility, not acquisition |

- The "viral" consumer AI apps were paid-creator businesses. Cal AI's founder is quoted saying influencers were "the real sauce"; Quittr reported about $4,000 per million views; Turbo AI runs seven full-time creators **[R]**.
- The copyable virality sits in small-group utilities with three properties: the creator needs other people to finish the job, the recipient gets value without installing, and the group already exists **[A, from the cases]**.
- Niche community apps grow slowly. Slopes took nine years to reach $1M a year; Letterboxd had 1.8M members nine years after launch **[R]**.
- Every failure studied (BeReal's decay, Gas, Poparazzi, Lapse, OpenAI's Sora app) had real virality and no recurring personal reason to return **[R]**.

## 3. Platform changes that matter for a solo developer

| Change | Why it matters | Source |
|---|---|---|
| **Free Apple-hosted model.** Small Business Program developers under 2M lifetime downloads can call Apple's cloud model (32K context) at no API cost on iOS 27+. The daily quota belongs to the user, is unpublished, and is shared with Siri and other apps. | AI features can cost nothing to run, but you cannot build a core loop that needs many cloud calls per day. | **[V]** [Apple, Private Cloud Compute](https://developer.apple.com/private-cloud-compute/) |
| **On-device model** (about 4K–8K token context), typed output, tool calling, image input; a single `LanguageModel` protocol across on-device, Apple cloud and third-party models. | Extraction and classification can run offline and free on supported iPhones. | **[V]** [Apple docs](https://developer.apple.com/documentation/FoundationModels) |
| **Siri AI** shipped with iOS 27 (14 Sep 2026); apps connect through App Intents. Third-party integrations are in developer preview. | General chat and "ask about my screen" wrappers lose their reason to exist. | **[R]** MacRumors; **[V]** [Apple](https://developer.apple.com/apple-intelligence/whats-new/) |
| **AlarmKit** (iOS 26): real alarms for third-party apps. | Removes the reliability moat of alarm apps; easy to clone. | **[V]** [Apple docs](https://developer.apple.com/documentation/alarmkit) |
| **Guideline 4.3(b)** (June 2026) names saturated categories, including "simple timers", that Apple may reject or remove. | Direct risk for thin single-purpose apps. | **[V]** [App Review Guidelines](https://developer.apple.com/app-store/review/guidelines/) |
| **Guideline 5.1.2(i)**: explicit consent before sending personal data to third-party AI. | Any app calling an outside LLM needs a consent step. | **[V]** same |
| **Guideline 5.1.1(ix)**: apps in regulated fields (finance, health) "should be submitted by a legal entity". | Publish finance or health apps under an LLC. | **[V]** same |
| **Dose calculators removed.** A peptide tracker's release notes say its calculators "have been removed to meet App Store guidelines". | Anything touching medication doses inherits this risk. | **[V]** OptiPin listing |
| **US external payment links** are allowed and currently carry no Apple commission; the Supreme Court has taken the case. | Do not build economics that only work at 0%. | **[R]** MacDailyNews, 14 Aug 2026 |
| **Texas SB 2420** (app-store age verification) in effect since 4 Jun 2026. | Small cost for adult utilities, real cost for social features. | **[V]** Apple Developer News |
| **Subscription benchmarks**: hard paywall converts 10.7% vs. 2.1% for freemium; median yearly price $34.80. | A hard paywall lifts revenue per install but removes the free users who spread the app. | **[V]** RevenueCat 2026 |

### Absorbed by platforms in 2025–26

| Category hit | By what |
|---|---|
| Event photo collection | iOS 27 Shared Albums (full resolution, expiry, Android and web contribution) **[R]** MacRumors |
| Flyer or roster photo to calendar | iOS 27 Visual Intelligence batch import **[R]** MacRumors |
| Group polls | Messages polls in iOS 26 **[R]** |
| Lab trackers, readiness scores, menopause logging | Apple Health redesign in the iOS 27.3 beta **[R]**; Health in ChatGPT (Jul 2026) **[R]** |
| "Connect accounts and analyse my money" | ChatGPT bank and brokerage connections (15 May 2026) **[R]** TechCrunch |
| Amazon price tracking | Amazon's own 365-day price history **[R]** |
| LeetCode on mobile | Official LeetCode iOS app (10 Apr 2026, 706 ratings) **[V]** |
| Job alerts | Simplify's native iOS app (25 Aug 2026, 36 ratings) **[V]** |

## 4. Category map (all 50 categories)

Verdicts: **Saturated** = strong incumbents or many funded entrants. **Contested** = several small entrants, no winner. **Pocket** = a specific gap with evidence. **Not researched** = the research agent was cut off before covering it.

| # | Category | Verdict | Key evidence |
|---:|---|---|---|
| 1 | Gym and bodybuilding | Saturated | Hevy 103,763 and Strong 108,548 ratings; Hevy anchors price near $24/yr **[V/R]** |
| 2 | Strength and hypertrophy | Saturated | Ten-plus trackers all updated within five weeks **[V]** |
| 3 | Running and hybrid | Saturated, one **pocket** | Strava owns Runna **[V]**; Hyrox has 5+ sim apps **[R]**; street-completion apps are unreliable or single-city **[V]** |
| 4 | Nutrition and meal tracking | Saturated | MyFitnessPal bought Cal AI **[R]** TechCrunch, 2 Mar 2026 |
| 5 | Weight loss and body composition | Saturated | 568+ new "GLP-1" apps since Jan 2026 **[R]**; peptide dose tools hit by review **[V]** |
| 6 | Sleep and recovery | Saturated | Shift-work planners: 5 entrants, at most 6 ratings **[V]** |
| 7 | Mental wellness | Saturated, legally risky | Seven states reported to ban AI therapy **[R]** |
| 8 | Habit formation | Saturated, one small pocket | Aligner timer leader has ad complaints **[V]** |
| 9 | Appearance and style | Saturated or contested | Alta free at 19,569 ratings; Parfumo free **[V]** |
| 10 | Sports and recreation | Contested (partly researched) | Golf side-bet apps: 10+; TeamSnap alternatives free **[R]** |
| 11 | Budgeting | Saturated | Monarch 118,486; aggregator fees per user **[V/R]** |
| 12 | Investing and stock analysis | Saturated | Data display licence about $500–2,500/month **[R]** |
| 13 | Quant trading and research | Contested | Wheel pain verified in users' words; 17+ tools **[V]** |
| 14 | FI and wealth tracking | Contested, low frequency | ProjectionLab web-only **[V]**; 8 FIRE calculators at 0–2 ratings **[V]** |
| 15 | Subscription and expense | Saturated | Splitwise alternatives: 8+ new **[R]** |
| 16 | Deals and price tracking | Saturated | Amazon built price history in **[R]** |
| 17 | Financial education | Contested, no consumer revenue evidence | Leader sells to banks **[R]** |
| 18 | Side hustles and income | Contested, one **pocket** | ServerLife users report lost tip history, Nov 2026 **[V]** |
| 19 | AI personal assistants | Saturated | Siri AI in iOS 27 **[R]** |
| 20 | AI agents and automation | Saturated | First-party mobile apps for coding agents **[R]**; 14+ usage monitors **[R]** |
| 21 | Productivity and time | Saturated | Tiimo, Structured; 23 office-day apps **[V]** |
| 22 | Developer tools | Contested | Several App Store Connect dashboards **[R]**; few buyers |
| 23 | Knowledge management | Saturated | Post-Pocket land grab; 8 saved-post organizers **[R]** |
| 24 | Personal analytics | Not researched | — |
| 25 | Email and communication | Partly researched | iOS 26 message screening **[R]** |
| 26 | Digital organization | Not researched | — |
| 27 | Social networking | Saturated | Cold-start networks owned by funded teams |
| 28 | Friend groups | Saturated | Widgetable 388,945; Howbout 51,840 **[V]** |
| 29 | Competitive social | Contested | Friend-bet apps already exist **[R]** |
| 30 | Dating and relationships | Saturated | Paired 210,899 **[V]**; Tea removed from the App Store **[R]** |
| 31 | Gaming | Contested (partly researched) | Riftbound: 6+ companions within a year **[R]** |
| 32 | Events and group planning | Saturated | Partiful 288,070; Apple Invites **[V]** |
| 33 | Photo and video | Saturated, absorbed | iOS 27 Shared Albums **[R]** |
| 34 | Social challenges | Contested | GymRats 4,668 iOS ratings **[V]** |
| 35 | College student tools | Contested, platform trap | Schools locking down Canvas tokens **[V]** UW-Madison |
| 36 | Study and exam prep | Saturated; exam-by-exam pockets | 11 AI study apps with 11K–1.1M ratings **[V]** |
| 37 | Career development | Contested, low pull | 6+ brag-document apps, none above 3 ratings **[V]** |
| 38 | Job searching | Contested | See table above |
| 39 | Interview prep | Saturated and shifting | Official LeetCode app **[V]** |
| 40 | Skill learning | Saturated, one **pocket** | No app for heritage speakers of smaller languages **[V]**; demand thin |
| 41 | Automotive | Saturated; pockets full of clones | Build pages, convoy apps, car-spotting games each have 5+ entrants **[R]** |
| 42 | Travel | Saturated | 20+ "saved posts to map" products **[R]** |
| 43 | Shopping | Saturated, capital-intensive | Funded AI shopping agents **[R]** |
| 44 | Food and restaurants | Saturated | ReciMe 335,043; Fig 16,900 **[V]** |
| 45 | Local discovery | Open for a bad reason | Per-city data collection does not scale for one person |
| 46 | Transportation | Contested to saturated | Train trackers and stop alarms already built **[R]** |
| 47 | Personal safety | Contested, hazardous | ICEBlock removed Oct 2025 **[R]** |
| 48 | Home organization | Saturated with low-traction clones | Low-frequency use |
| 49 | Scheduling and coordination | Contested, one **pocket** | Co-parenting incumbents all removed free tiers; 94–99 of 100 recent reviews are 3 stars or lower **[V]** |
| 50 | Hobbies and niche communities | Contested; small pockets | Anime figures, smart telescopes, dog sports **[V]** |

## 5. What this means

1. The premise "find an underserved niche and build a tracker" is now the default strategy of thousands of developers. Most such niches have clones and no winner.
2. The pockets that survive share at least one of these: **a hard technical core** (reliable GPS-to-street matching, broker-export reconciliation), **a live incumbent failure with locked-in demand** (co-parenting, tip tracking), or **a community reachable in person** rather than through subreddits that ban promotion.
3. Personal fit carries more weight than usual. When building is cheap, the developer who uses the product daily notices the reliability problems that the review data shows users punish.
