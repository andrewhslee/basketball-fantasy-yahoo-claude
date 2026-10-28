# Draft: Yahoo Fantasy Sports API access application

Form: <https://sports.yahoo.com/developer/access/>

Yahoo closes vague applications without replying, so be specific. Edit the parts in [brackets].

---

**Product / what you're building**
A personal assistant that helps me manage my own Yahoo Fantasy Basketball team in one private league ([league name], league ID [12345]). It runs only on my computer, as a local tool for Claude (Anthropic's AI assistant), and signs in with my own Yahoo account through OAuth. It isn't distributed, sold or offered to anyone else.

**Fantasy data needed**
My team's roster and lineup by date, player stats (season, last 7 and 30 days, daily), my league's settings, standings and weekly matchups, and the free-agent / waiver player list with ownership. It only reads my own league.

**Intended audience / expected users (first 3–6 months)**
Small (under 1,000). In practice, one user: me.

**YDN Client ID**
[paste your Client ID]

**Notes (read/write request)**
I'm requesting read/write access for my own team only, so I can (1) set my daily NBA lineup (PUT team/{team_key}/roster) and (2) make add/drop moves and waiver claims (POST league/{league_key}/transactions). Every change is shown to me and confirmed by me before it's sent, and it only affects my own team. Request volume is low: a few dozen reads and a handful of writes per day.
