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
