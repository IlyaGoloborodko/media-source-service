# media-source-service

Provider-agnostic media **search** and **stream-URL resolution** service. Extracted
from the Discord bot (`discordAudio`) so any client can query media sources over HTTP
instead of shelling out to `yt-dlp` itself.

Today it wraps YouTube (via `yt-dlp` as a library). New sources are added by
implementing one `Provider` interface — the HTTP contract does not change.

> The service **does not proxy audio bytes**. It resolves a direct CDN stream URL;
> the client (e.g. the bot's ffmpeg) reads bytes straight from that URL.

## API

| Method | Path       | Query                                   | Returns |
|--------|------------|-----------------------------------------|---------|
| GET    | `/health`  | —                                       | `{status, providers}` |
| GET    | `/search`  | `q` (required), `provider=youtube`, `limit` | `{provider, query, results: [Track]}` |
| GET    | `/stream`  | `id` (required), `provider=youtube`     | `{provider, id, stream_url, expires_at}` |
| GET    | `/playlist`| `url` (required, URL or id), `provider=youtube`, `limit` | `{provider, playlist, results: [Track]}` |
| GET    | `/similar` | `artist` (required), `track` (required), `limit` | `{results: [Track]}` |
| GET    | `/charts`  | `tag` and/or `country`, `limit`         | `{results: [Track]}` |
| GET    | `/tags`    | `artist` (required), `track`, `limit` (default 10) | `{tags: [{name, weight}]}` |

`Track`: `{provider, id, title, uploader?, url?, duration?, thumbnail?}`

Errors: `422` invalid params, `404` unknown provider, `502` upstream/provider
failure, `503` Last.fm API key not configured (discovery endpoints).
Interactive docs at `/docs`.

### Discovery (Last.fm → playable YouTube tracks)

`/similar` and `/charts` use **Last.fm** to *pick* music (recommendations, genre/
mood charts, global or per-country top tracks), then resolve each suggestion to a
real, streamable **YouTube** track via the existing search. So their `results` are
ordinary `Track`s (`provider="youtube"`) that the bot can `/stream` unchanged.

Last.fm is metadata-only; unresolved suggestions are dropped. Requires a Last.fm
API key (`MSS_LASTFM_API_KEY`, see Configuration) — without it these two
endpoints return `503`.

- `/charts` precedence when several are given: `tag` → `country` → global.
- `country` is an ISO country *name* (e.g. `Germany`), per Last.fm `geo.getTopTracks`.

**Dirty names are accepted.** `/similar` normalises `artist`/`track` the same way
`/tags` does (see below), so raw YouTube metadata such as
`artist="Death From Above 1979 - Topic"` resolves instead of silently matching
nothing.

**Unknown vs broken are distinguishable** — deliberately:

| Situation | Response |
|-----------|----------|
| Last.fm has no such artist/track/tag | `200` with `{"results": []}` |
| Last.fm timeout, unreachable, 5xx, rate limit | `502` |
| Last.fm API key not configured | `503` |

An unknown name is a valid empty answer, not a failure; flattening a real outage
into an empty list too would make outages invisible, so those stay errors.

### `/tags` — genre/style tags

Returns Last.fm tags for an artist (`artist.getTopTags`) or a specific track
(`track.getTopTags`, when `track` is given). Unlike the other endpoints the
payload is **not** tracks:

```json
{"tags": [{"name": "thrash metal", "weight": 100},
          {"name": "metal", "weight": 87},
          {"name": "seen live", "weight": 41}]}
```

`weight` is Last.fm's tag count (0-100), sorted descending — it exists so a
consumer can build a *weighted* genre profile instead of treating "seen live"
and "thrash metal" as equals.

Tags are returned **as-is**: no genre whitelist, no filtering of noise tags.
Weighting and filtering are the consumer's job.

**Names may be dirty.** Anything YouTube produced is accepted and normalised
here (see `providers/naming.py`): `- Topic` and `VEVO` suffixes, marketing tails
like `[OFFICIAL VIDEO]` / `(Official Music Video)` / `[HD]`, and `Artist - Track`
titles from which the artist is extracted. Meaningful brackets such as `(Remix)`
and `(feat. …)` are preserved, and hyphenated names (`Dinosaur Pile-Up`) are
never split.

**Unknown is not an error.** If Last.fm has no entry after normalisation, the
response is `200` with `{"tags": []}` — an unknown genre simply doesn't enrich
the profile, and shouldn't force the consumer to handle a failure that isn't one.

```
GET /tags?artist=Slipknot
GET /tags?artist=Slipknot&track=Psychosocial&limit=5
GET /tags?artist=Death+From+Above+1979+-+Topic
```

### Example

```
GET /search?q=daft+punk&limit=2
GET /stream?id=dQw4w9WgXcQ
GET /playlist?url=PLxxxx&limit=20
GET /similar?artist=Daft+Punk&track=Da+Funk&limit=10
GET /charts?tag=synthwave&limit=10
GET /charts?country=Germany&limit=10
```

## Run

```bash
uv sync
uv run media-source-service        # serves on 0.0.0.0:9000
uv run pytest                      # tests (network-free)
```

Docker:

```bash
docker build -t media-source-service .
docker run -p 9000:9000 media-source-service
```

## Configuration

Env vars (prefix `MSS_`, or a `.env` file — see `.env.example`):

| Var | Default | Meaning |
|-----|---------|---------|
| `MSS_HOST` | `0.0.0.0` | bind host |
| `MSS_PORT` | `9000` | bind port (pinned to 9000 in docker-compose) |
| `MSS_DEFAULT_SEARCH_LIMIT` | `10` | results when client omits `limit` |
| `MSS_MAX_SEARCH_LIMIT` | `25` | hard cap on `limit` |
| `MSS_YTDLP_COOKIEFILE` | _unset_ | path to a cookies.txt (see below) |
| `MSS_YTDLP_COOKIES_FROM_BROWSER` | _unset_ | browser to read cookies from, e.g. `chrome` (host only) |
| `MSS_LASTFM_API_KEY` | _unset_ | Last.fm API key for `/similar` and `/charts` ([create one](https://www.last.fm/api/account/create)) |

## YouTube authentication (cookies)

Unauthenticated requests get rate-limited and then blocked by YouTube with
*"Sign in to confirm you're not a bot"*. The first request from an IP usually
succeeds, but rapid or repeated `/stream` calls hit the wall. Giving yt-dlp a
real session via cookies raises those limits and is the reliable fix.

Set **exactly one** of the two env vars (yt-dlp forbids combining them):

- `MSS_YTDLP_COOKIES_FROM_BROWSER` — read cookies straight from a local browser.
  Convenient for **local/host** runs (`chrome`, `firefox`, `firefox:profile`).
  Does **not** work in Docker — there's no browser in the container.
- `MSS_YTDLP_COOKIEFILE` — path to a Netscape-format `cookies.txt`. The option
  to use **in Docker**.

### Exporting a cookies.txt that stays valid

YouTube rotates cookies on any open youtube.com tab, which silently invalidates
exported cookies. Follow yt-dlp's official procedure to avoid that
([wiki](https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies)):

1. Open a **private/incognito** window and log into YouTube (use a **throwaway
   account** — the cookies grant access to it, and accounts can get banned).
2. In the **same tab**, open `https://www.youtube.com/robots.txt` (and nothing
   else — don't browse YouTube further).
3. Export cookies for `youtube.com` with a Netscape-format extension such as
   *"Get cookies.txt LOCALLY"*. The first line must be `# Netscape HTTP Cookie File`.
4. **Close** the incognito window so the session is never reopened.

### Docker notes

- Save `cookies.txt` next to `docker-compose.yml`, then uncomment the
  `environment` (`MSS_YTDLP_COOKIEFILE=/app/cookies.txt`) and `volumes`
  (`./cookies.txt:/app/cookies.txt:ro`) lines and `docker compose up -d --build`.
- The file must use **Unix (LF)** line endings inside the Linux container;
  a Windows (CRLF) file causes HTTP 400 errors. Convert if needed.
- Cookies expire — re-export when `/stream` starts failing again.
- `cookies.txt` is git-ignored; still, don't share it (it contains your session).

## Logging

Everything goes to the console; the important parts can be mirrored to a
Telegram chat. Same setup and the same env var names as `DiscordAiService`, so
both services are configured identically.

| Var | Default | Meaning |
|-----|---------|---------|
| `LOG_LEVEL` | `INFO` | what shows up in the console |
| `TELEGRAM_BOT_TOKEN` | _empty_ | from @BotFather; empty turns Telegram off |
| `TELEGRAM_CHAT_ID` | _empty_ | from @userinfobot, or a group id (negative) |
| `TELEGRAM_LOG_LEVEL` | `ERROR` | what gets forwarded to Telegram |

These are **not** `MSS_`-prefixed (the prefix applies to `Settings` only); they
are read straight from the environment after `load_dotenv()`.

The two levels are independent, so the console can stay chatty while Telegram
only gets what matters. Telegram logging is optional: without both a token and a
chat id the service runs exactly as before.

Delivery never blocks a request — records go onto a queue and a background
thread sends them, at most one every 3s (Telegram allows ~20/min per chat). If
Telegram is down, slow, or the queue fills up, messages are dropped and the
service keeps running: logging must never be the reason something fails.

`httpx`/`httpcore` are pinned to `WARNING` because they log full request URLs at
`INFO` — and the Last.fm `api_key` travels in the query string.

## Layout

```
src/media_source/
  main.py              # FastAPI app + lifespan (registry + discovery wiring)
  config.py            # pydantic-settings
  logging_setup.py     # console + optional Telegram log handler
  api/routes.py        # /health /search /stream /playlist /similar /charts /tags
  models/schemas.py    # Track, SearchResponse, StreamResponse, ...
  providers/
    base.py            # Provider ABC + ProviderError
    youtube.py         # yt-dlp-backed implementation
    lastfm.py          # Last.fm metadata client (httpx): similar/charts/tags
    naming.py          # normalise YouTube-derived names for Last.fm lookups
    registry.py        # name -> provider lookup
  services/
    discovery.py       # Last.fm candidates -> playable YouTube Tracks
```

## Adding a provider

1. Implement `Provider` (`name`, `async search`, `async resolve_stream`) in a new
   `providers/<name>.py`.
2. Register it in `providers/registry.py`.
3. Clients select it via `?provider=<name>`.
