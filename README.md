# Yahoo Fantasy Basketball MCP

An MCP server that lets Claude look after your Yahoo Fantasy NBA team: show the stats you care about, check and plan lineup changes and add/drops, and suggest lineups, pickups and trades.

**Yahoo's Fantasy API is read-only for new apps.** So this server reads everything through the API. Changes are planned and checked here, then made on the Yahoo website, either by Claude in your browser using Claude in Chrome, or by you. If Yahoo ever grants this app write access, direct write tools can be added (see the end of this file).

## How it fits together

```
You ──chat──▶ Claude Code ──stdio──▶ this server ──HTTPS──▶ Yahoo Fantasy API (read)
                  │
                  └──Claude in Chrome──▶ basketball.fantasysports.yahoo.com (changes, with your OK)
```

Claude Code starts the server in the background when a session starts. Each `@tool` function in [server.py](src/yahoo_fantasy_mcp/server.py) becomes a tool Claude can call. Claude reads the tool's name, parameters and docstring to decide when to use it.

## Setup

1. **Create a Yahoo app** at <https://developer.yahoo.com/apps/create/>:
   - API permissions: **Fantasy Sports – Read**
   - Redirect URI: `https://localhost:8000/callback`. If Yahoo rejects it, use `https://127.0.0.1:8000/callback` and set the same value in `.env`.
2. **Add your credentials:** `cp .env.example .env`, then paste in the Client ID and Client Secret.
3. **Sign in to Yahoo once:**
   ```bash
   uv run yahoo-fantasy-mcp login
   ```
   Approve the app in the browser. The browser then goes to a localhost page that won't load, which is expected. Copy that page's URL from the address bar and paste it into the terminal. Tokens are saved to `~/.config/yahoo-fantasy-mcp/tokens.json` (only you can read it) and refresh automatically.
4. **Register the server with Claude Code** (once, for every project):
   ```bash
   claude mcp add yahoo-fantasy -s user -- uv --directory /Users/hanselee/projects/yahoo-claude run yahoo-fantasy-mcp
   ```
5. **Optional: apply for write access** at <https://sports.yahoo.com/developer/access/>. A draft of the application is in [docs/yahoo-access-application.md](docs/yahoo-access-application.md).

## Testing

| Layer | Command | What it checks |
|---|---|---|
| Unit tests | `uv run pytest` | Parsing Yahoo responses, lineup and add/drop rules, and tools called through a real MCP client against saved responses in `tests/fixtures/`. Doesn't touch Yahoo. |
| MCP Inspector | `npx @modelcontextprotocol/inspector uv --directory . run yahoo-fantasy-mcp` | A web page where you can call each tool by hand and see exactly what Claude would get back. The best tool for debugging. |
| Claude Code | `claude mcp list` should show `yahoo-fantasy … ✓ Connected` | The real thing. Ask Claude to "check my Yahoo connection". |

After you change the server code, start a new Claude Code session so the server restarts with the new code.

## Using it

Just ask:

- "Show my roster for tomorrow."
- "Only ever show me PTS, REB, AST, 3PTM and FG%." Claude saves this as your favorite stats.
- "How has my team done over the last week?"
- "How's my matchup going? Which categories are close?"
- "Find free-agent centers who block shots."
- "Start Brunson at G tomorrow and bench Poole." Claude checks the move, shows you the plan, waits for your yes, makes the change on Yahoo in Chrome, then re-reads your roster to confirm.

Slash commands come from the server's prompts. Type `/mcp__yahoo-fantasy__` to see them:

| Command | What it does |
|---|---|
| `/mcp__yahoo-fantasy__optimize_lineup` | Suggests the best lineup for a day |
| `/mcp__yahoo-fantasy__waiver_targets` | Suggests pickups for your weak categories |
| `/mcp__yahoo-fantasy__trade_ideas` | Suggests trades that fix weak categories |
| `/mcp__yahoo-fantasy__make_changes` | Plans a change, confirms it with you, makes it, then verifies it |

Claude Code asks permission the first time each tool runs. It's safe to choose "always allow" for these tools, because none of them can change anything on Yahoo. Browser actions are separate and still ask you.

## Tools

| Tool | Purpose |
|---|---|
| `check_connection` | Checks credentials, sign-in and API access |
| `list_my_teams`, `set_default_team` | Find your NBA teams and choose the default |
| `get_league_settings` | Categories, roster slots, waivers/FAAB, add limit |
| `get_roster` | Lineup for a date, with eligibility, injuries and locks |
| `get_team_stats` | Per-player stats (and team totals) for season, last 7 days, last 30 days or a single date, filtered to the stats you pick |
| `set_stat_preferences`, `get_stat_preferences` | Save and show your favorite stats |
| `search_players` | Free agents, waiver players or anyone by name, sortable by any stat |
| `get_matchup` | This week's category-by-category score and games remaining |
| `get_standings` | League table, with team keys for looking at other rosters |
| `plan_lineup_change` | Checks start/bench moves and works out implied swaps |
| `plan_add_drop` | Checks a pickup or drop: free agent vs waiver claim, roster space |

## Project layout

```
src/yahoo_fantasy_mcp/
  __main__.py   `login` command, otherwise runs the server
  config.py     paths and credentials (.env)
  auth.py       Yahoo OAuth: login, token storage, refresh
  client.py     HTTP calls to the Fantasy API (XML)
  parse.py      Yahoo XML -> small dicts; stat-name matching
  lineup.py     lineup and add/drop rules (no network, easy to test)
  prefs.py      default team + favorite stats (~/.config/yahoo-fantasy-mcp/prefs.json)
  server.py     MCP tools and prompts
tests/          pytest suite + sample Yahoo responses
```

## Not yet confirmed against live Yahoo

The test fixtures were written from Yahoo's documented response format, not captured from your account. After your first login, check these:

- That each tool returns sensible data. If something looks off, save the raw response as a fixture and fix the parser.
- The add-player link `…/addplayer?apid=<id>` and the team page `?date=` parameter used in the change plans.
- Whether `team_remaining_games` (games left this week) shows up in your league's matchup data.

## If Yahoo grants write access

Add `set_lineup` (`PUT team/{team_key}/roster`) and `add_drop` (`POST league/{league_key}/transactions`) tools to `server.py`. They should reuse the checks in `lineup.py`, be marked `destructive_hint=True`, and never be auto-allowed.

## Troubleshooting

- **"Not signed in" / token errors:** run `uv run yahoo-fantasy-mcp login` again.
- **403 "not authorized":** the app isn't approved for Fantasy data yet. Apply at the access page above. Some older apps started working again after signing in once more.
- **HTTP 999:** Yahoo is rate-limiting you. Wait a few minutes.
- **Server shows as failed in `claude mcp list`:** run `uv --directory /Users/hanselee/projects/yahoo-claude run yahoo-fantasy-mcp` in a terminal to see the error (press Ctrl-C to stop it).
