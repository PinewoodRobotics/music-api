# Music API v2 reference

Every JSON response is `{"result": ...}` on success or `{"error": "..."}` with a 4xx/5xx status.
When a token is set, send `Authorization: Bearer <token>` (or `?token=` for `EventSource` / `<img>`).
IDs can be bare Spotify IDs; bodies that take `uri`/`uris` also accept `spotify:` URIs and open.spotify.com links.

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
| `GET` | `/api/queue` | Upcoming (and, with Soloist, previous) queue entries. ?limit=n (Soloist: up to 80) |
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
| `GET` | `/api/events` | Server-sent events: `status` (1/s while anyone listens), `track`, `queue`, `sleep`, `error` |
| `ANY` | `/api/spotify/{path}` | Raw Spotify Web API passthrough with your login, e.g. `GET /api/spotify/me/player/devices` |

## Auth (Web API login)

| Method | Path | Notes |
|---|---|---|
| `GET` | `/auth` | Login status, scopes, redirect URI |
| `GET` | `/auth/login` | Login page; `?redirect=1` goes straight to Spotify |
| `GET` | `/auth/callback` | OAuth redirect target (checked by PKCE state, no token needed) |
| `POST` | `/auth/paste` | Body `{url}`: finish login by pasting the redirected URL (headless boxes) |
| `POST` | `/auth/logout` | Forget the Web API tokens |
