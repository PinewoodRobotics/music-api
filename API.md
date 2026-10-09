# Music API v2 reference

Base URL: `https://music-api.pinewoodrobotics.org` (or `http://127.0.0.1:8765` on the machine itself). For a self-contained guide written for LLM agents, see [llms-full.txt](https://music-api.pinewoodrobotics.org/llms-full.txt).

Every JSON response is `{"result": ...}` on success or `{"error": "..."}` with a 4xx/5xx status (exceptions: `GET /api` returns a bare array; `/api/artwork` returns a redirect or image bytes; `/auth/login` returns HTML).
Send an API token as `Authorization: Bearer <token>` (or `?token=` for `EventSource` / `<img>` / browser links). A token is required as soon as any token exists, when started with `--public`, or when listening beyond localhost.
Path `{id}`s are bare 22-character Spotify IDs. `uri`/`uris`/`context` fields take `spotify:` URIs or open.spotify.com links; `/api/play` `uris`, `/api/queue` and `offset` also accept bare IDs (as tracks).

## Playback

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/status` | Playback state, position, volume, shuffle/repeat, current track/episode, context, device, backend |
| `GET` | `/api/now-playing` | Just the current track/episode (or null) |
| `GET` | `/api/artwork` | Current cover image: 302 to Spotify's CDN, or ?proxy=1 to get the bytes (for devices without HTTPS) |
| `GET` | `/api/lyrics` | Lyrics for the current song (or ?track=id), synced line-by-line when available (lrclib.net). Includes position_ms and the index of the current line |
| `GET` | `/api/sleep` | Sleep timer state |
| `POST` | `/api/sleep` | Body {minutes, fade?: seconds}: pause after N minutes, fading out over the last `fade` seconds (default 30) |
| `DELETE` | `/api/sleep` | Cancel the sleep timer |
| `POST` | `/api/play` | Play/resume. Body optional: {uri} (track, album, playlist, artist, episode, show; URI or open.spotify.com link), {uris: [...]}, {context, offset: index\|uri}, {position: seconds \| position_ms} |
| `POST` | `/api/play-url` | Body {url}: play any open.spotify.com / spotify: link |
| `POST` | `/api/pause` | Pause |
| `POST` | `/api/next` | Skip to next |
| `POST` | `/api/previous` | Previous track (restarts the current one if it's past the first few seconds) |
| `POST` | `/api/back` | Alias of /api/previous (v1 compatibility) |
| `POST` | `/api/seek` | Body {position: seconds} \| {position_ms} \| {delta: ±seconds} |
| `POST` | `/api/volume` | Body {volume: 0-100} \| {delta: ±n} |
| `POST` | `/api/shuffle` | Body {enabled?: bool}; omit to toggle |
| `POST` | `/api/repeat` | Body {mode?: off\|context\|track} (one/all accepted); omit to cycle |

## Queue & devices

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/queue` | Upcoming (and, with Soloist, previous) queue entries, each with added_by {name, avatar} when someone queued it through this API. ?limit=n (Soloist: up to 80) |
| `POST` | `/api/queue` | Body {uri} \| {uris: [...]}: add to the end of the queue |
| `GET` | `/api/devices` | Spotify Connect devices on the account (plus the local Soloist device) |
| `POST` | `/api/devices/transfer` | Body {device: name\|id\|"soloist", play?: bool}: move playback to a device |
| `GET` | `/api/backend` | Which playback backend is in use and how it's doing |
| `POST` | `/api/backend/soloist/{verb}` | activate \| deactivate: claim or release active-device status for Soloist |

## Catalog

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/search` | ?q=&type=track,album,artist,playlist,...&limit=(max 10)&offset=. Returns {type: page} |
| `GET` | `/api/tracks/{id}` | One track; id may be 'current'. Adds saved: bool |
| `PATCH` | `/api/tracks/{id}` | Body {saved: bool}: like/unlike (save to / remove from Liked Songs); id may be 'current' |
| `GET` | `/api/albums/{id}` | Album with its first page of tracks |
| `GET` | `/api/albums/{id}/tracks` | ?limit=&offset= |
| `GET` | `/api/artists/{id}` | One artist |
| `GET` | `/api/artists/{id}/albums` | ?include_groups=album,single,appears_on,compilation&limit=&offset= |
| `GET` | `/api/episodes/{id}` | One podcast episode |
| `GET` | `/api/shows/{id}` | Podcast with its first page of episodes |
| `GET` | `/api/audiobooks/{id}` | Audiobook with authors, narrators and its first page of chapters |
| `GET` | `/api/audiobooks/{id}/chapters` | ?limit=&offset= |
| `GET` | `/api/chapters/{id}` | One audiobook chapter |
| `GET` | `/api/shows/{id}/episodes` | ?limit=&offset= |

## Playlists

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/playlists` | Your playlists. ?limit=&offset= |
| `POST` | `/api/playlists` | Body {name, description?, public?, collaborative?} |
| `GET` | `/api/playlists/{id}` | Playlist details (no items; see /items) |
| `PATCH` | `/api/playlists/{id}` | Body {name?, description?, public?, collaborative?} |
| `DELETE` | `/api/playlists/{id}` | Remove from your library (Spotify has no hard delete; for your own playlists this is the same thing) |
| `GET` | `/api/playlists/{id}/items` | ?limit=&offset=. Spotify only returns items for playlists you own or collaborate on |
| `POST` | `/api/playlists/{id}/items` | Body {uris: [...], position?: n} |
| `DELETE` | `/api/playlists/{id}/items` | Body {uris: [...]} (removes every occurrence) |
| `PUT` | `/api/playlists/{id}/items` | Body {range_start, insert_before, range_length?} to move items, or {uris: [...]} to replace all |
| `GET` | `/api/playlists/{id}/image` | Cover image URLs |
| `PUT` | `/api/playlists/{id}/image` | Body {jpeg_base64}: upload a custom cover (JPEG, max 256 KB) |
| `POST` | `/api/playlists/{id}/play` | Body {offset?: index\|uri, shuffle?: bool} |

## Library & history

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/library/{kind}` | kind = tracks \| albums \| episodes \| shows \| audiobooks \| playlists \| artists (followed). ?limit=&offset= (artists: ?after=) |
| `PUT` | `/api/library` | Body {uris: [...]}: save tracks/albums/episodes/shows/playlists, follow artists/users (max 40) |
| `DELETE` | `/api/library` | Body {uris: [...]}: remove / unfollow (max 40) |
| `GET` | `/api/library/contains` | ?uris=a,b,c → {uri: bool} |
| `GET` | `/api/recent` | Recently played tracks. ?limit=(max 50)&before=&after= (unix ms) |
| `GET` | `/api/top/{kind}` | kind = tracks \| artists. ?time_range=short_term\|medium_term\|long_term&limit=&offset= |
| `GET` | `/api/me` | Spotify profile of the logged-in Web API user |

## Tokens

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/tokens` | All API tokens (no secrets): id, name, prefix, created, last_used, current |
| `POST` | `/api/tokens` | Body {name?}: create a token. The response is the only time the token itself is shown |
| `DELETE` | `/api/tokens/{id}` | Revoke a token immediately (any token may revoke any other, or itself; never the last one) |

Tokens have no scopes: any token can do everything, including creating and revoking tokens. Only SHA-256 hashes are stored (`<data-dir>/api-tokens.json`, mode 600). New tokens look like `mapi_…`. A `--token` / `$MUSIC_API_TOKEN` static token also works but isn't listed and can't be revoked here. Revoking the last listed token is refused (409) unless a static token is configured.

## System audio

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/system/volume` | Machine's output volume (PipeWire / PulseAudio / macOS), separate from Spotify's own volume |
| `POST` | `/api/system/volume` | Body {volume?: 0-100, delta?: ±n, muted?: bool} |
| `GET` | `/api/system/outputs` | Audio outputs (sinks) on this machine, e.g. the USB speakers (Linux) |
| `POST` | `/api/system/outputs` | Body {id}: make that output the default (Linux) |

## Other

| Method | Path | Notes |
|---|---|---|
| `POST` | `/api/playpause` | Toggle play/pause |
| `GET` | `/api/app/me` | Who's signed in: {id, name, avatar, admin, kind: slack\|token}. API tokens show as @admin |
| `GET` | `/api/app/playlists` | Playlists shown in the web app (the account's own are hidden), newest first, with created_by, source_url, can_edit |
| `POST` | `/api/app/playlists` | Body {name, description?}: create a playlist credited to you |
| `POST` | `/api/app/playlists/import` | Body {url}: copy a public Spotify playlist (first 100 tracks) → {playlist, imported, total, truncated} |
| `GET` | `/api/app/playlists/{id}` | One app playlist |
| `PATCH` | `/api/app/playlists/{id}` | Body {name?, description?} (creator or admin) |
| `DELETE` | `/api/app/playlists/{id}` | Delete (creator or admin) |
| `GET` | `/api` | This list as JSON: a bare array of `{method, path, doc}` (no `result` envelope) |
| `GET` | `/api/events` | Server-sent events: `status` (every 1 s with Soloist, 2 s with connect, while anyone listens), `track`, `queue` (Soloist only), `sleep`, `error`. Use `?token=` with `EventSource` |
| `ANY` | `/api/spotify/{path}` | Raw Spotify Web API passthrough with your login, e.g. `GET /api/spotify/me/player/devices` |

## Auth (Web API login)

| Method | Path | Notes |
|---|---|---|
| `GET` | `/auth` | Login status, scopes, redirect URI |
| `GET` | `/auth/login` | Login page; `?redirect=1` goes straight to Spotify |
| `GET` | `/auth/callback` | OAuth redirect target (checked by PKCE state, no token needed) |
| `POST` | `/auth/paste` | Body `{url}`: finish login by pasting the redirected URL (headless boxes) |
| `POST` | `/auth/logout` | Forget the Web API tokens |

## No token needed

| Method | Path | Notes |
|---|---|---|
| `GET` | `/` | Web remote (open `/?token=…` once; the page remembers it) |
| `GET` | `/llms.txt` | llms.txt index for LLM agents |
| `GET` | `/llms-full.txt` | Complete agent-oriented reference in one file |
| `GET` | `/LLMS.md` | Same content as `/llms-full.txt`, served as Markdown |
| `GET` | `/API.md` | This file |
| `GET` | `/README.md` | Overview, setup and deployment |
| `GET` | `/auth/callback` | OAuth redirect target |
| `OPTIONS` | `*` | CORS preflight (`Access-Control-Allow-Origin: *` on every response) |
