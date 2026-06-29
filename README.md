# media-source-service

Provider-agnostic media **search** and **stream-URL resolution** service. Extracted
from the Discord bot (`discordAudio`) so any client can query media sources over HTTP
instead of shelling out to `yt-dlp` itself.

Today it wraps YouTube (via `yt-dlp` as a library). New sources are added by
implementing one `Provider` interface — the HTTP contract does not change.

> The service **does not proxy audio bytes**. It resolves a direct CDN stream URL;
> the client (e.g. the bot's ffmpeg) reads bytes straight from that URL.

## API

| Method | Path      | Query                                   | Returns |
|--------|-----------|-----------------------------------------|---------|
| GET    | `/health` | —                                       | `{status, providers}` |
| GET    | `/search` | `q` (required), `provider=youtube`, `limit` | `{provider, query, results: [Track]}` |
| GET    | `/stream` | `id` (required), `provider=youtube`     | `{provider, id, stream_url, expires_at}` |

`Track`: `{provider, id, title, uploader?, url?, duration?, thumbnail?}`

Errors: `422` invalid params, `404` unknown provider, `502` upstream/provider failure.
Interactive docs at `/docs`.

### Example

```
GET /search?q=daft+punk&limit=2
GET /stream?id=dQw4w9WgXcQ
```

## Run

```bash
uv sync
uv run media-source-service        # serves on 0.0.0.0:8080
uv run pytest                      # tests (network-free)
```

Docker:

```bash
docker build -t media-source-service .
docker run -p 8080:8080 media-source-service
```

## Configuration

Env vars (prefix `MSS_`, or a `.env` file — see `.env.example`):

| Var | Default | Meaning |
|-----|---------|---------|
| `MSS_HOST` | `0.0.0.0` | bind host |
| `MSS_PORT` | `8080` | bind port |
| `MSS_DEFAULT_SEARCH_LIMIT` | `10` | results when client omits `limit` |
| `MSS_MAX_SEARCH_LIMIT` | `25` | hard cap on `limit` |
| `MSS_YTDLP_COOKIEFILE` | _unset_ | path to a cookies.txt (see below) |
| `MSS_YTDLP_COOKIES_FROM_BROWSER` | _unset_ | browser to read cookies from, e.g. `chrome` (host only) |

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

## Layout

```
src/media_source/
  main.py              # FastAPI app + lifespan (builds provider registry)
  config.py            # pydantic-settings
  api/routes.py        # /health /search /stream
  models/schemas.py    # Track, SearchResponse, StreamResponse
  providers/
    base.py            # Provider ABC + ProviderError
    youtube.py         # yt-dlp-backed implementation
    registry.py        # name -> provider lookup
```

## Adding a provider

1. Implement `Provider` (`name`, `async search`, `async resolve_stream`) in a new
   `providers/<name>.py`.
2. Register it in `providers/registry.py`.
3. Clients select it via `?provider=<name>`.
