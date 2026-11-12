# Music API v2 reference

Base URL: `https://music.pinewoodrobotics.org` (or `http://127.0.0.1:8765` on the machine itself). For a self-contained guide written for LLM agents, see [llms-full.txt](https://music.pinewoodrobotics.org/llms-full.txt).

Every JSON response is `{"result": ...}` on success or `{"error": "..."}` with a 4xx/5xx status (exceptions: `GET /api` returns a bare array; `/api/artwork` returns a redirect or image bytes; `/auth/login` returns HTML).
Send an API token as `Authorization: Bearer <token>` (or `?token=` for `EventSource` / `<img>` / browser links). A token is required as soon as any token exists, when started with `--public`, or when listening beyond localhost.
Path `{id}`s are bare 22-character Spotify IDs. `uri`/`uris`/`context` fields take `spotify:` URIs or open.spotify.com links; `/api/play` `uris`, `/api/queue` and `offset` also accept bare IDs (as tracks).

## Playback

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/status` | Playback state, position, volume, shuffle/repeat, current track/episode, context, device, backend |
| `GET` | `/api/now-playing` | Just the current track/episode (or null) |
| `GET` | `/api/artwork` | Current cover image: 302 to Spotify's CDN, or ?proxy=1 to get the bytes (for devices without HTTPS). During AirPlay: the sender's cover art bytes |
| `GET` | `/api/lyrics` | Lyrics for the current song (or ?track=id), synced line-by-line when available (lrclib.net). Includes position_ms and the index of the current line |
| `GET` | `/api/sleep` | Sleep timer state |
| `POST` | `/api/sleep` | Body {minutes, fade?: seconds}: pause after N minutes, fading out over the last `fade` seconds (default 30) |
| `DELETE` | `/api/sleep` | Cancel the sleep timer |
| `POST` | `/api/play` | Play/resume. Body optional: {uri} (track, album, playlist, artist, episode, show; URI or open.spotify.com link), {uris: [...]}, {context, offset: index\|uri}, {position: seconds \| position_ms}, {shuffle?: bool} (set before playing). During AirPlay only the empty body works (resumes the sender); anything else is 409 airplay_active |
| `POST` | `/api/play-url` | Body {url}: play any open.spotify.com / spotify: link |
| `POST` | `/api/pause` | Pause. During AirPlay: pauses the sender |
| `POST` | `/api/next` | Skip to next (the AirPlay sender's, during AirPlay) |
| `POST` | `/api/previous` | Previous track (restarts the current one if it's past the first few seconds). During AirPlay: the sender's |
| `POST` | `/api/back` | Alias of /api/previous (v1 compatibility) |
| `POST` | `/api/seek` | Body {position: seconds} \| {position_ms} \| {delta: ±seconds} |
| `POST` | `/api/volume` | Body {volume: 0-100} \| {delta: ±n} |
| `POST` | `/api/shuffle` | Body {enabled?: bool}; omit to toggle |
| `POST` | `/api/repeat` | Body {mode?: off\|context\|track} (one/all accepted); omit to cycle |
| `GET` | `/api/activity` | What people did in the last 24 h, oldest first: {entries: [{id, at (unix ms), by {id, name, avatar}, action, detail, origin: web\|slack\|api\|media-session}], latest}. ?since=<id> returns only newer entries; ?limit= (default and max 500). Also pushed live as the `activity` SSE event |

## Queue & devices

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/queue` | Upcoming (and, with Soloist, previous) queue entries, each with added_by {id, name, avatar} when someone queued it through this API. ?limit=n (Soloist: up to 80) |
| `POST` | `/api/queue` | Body {uri} \| {uris: [...]}: add to the end of the queue |
| `POST` | `/api/queue/remove` | Body {uid} \| {uids: [...]} \| {index}: remove entries from Up Next (any signed-in user). Soft: they're hidden from every queue view and skipped the moment they start. 404 if one isn't in Up Next. Returns the queue |
| `POST` | `/api/queue/jump` | Body {uid} (Soloist) or {index}: skip ahead to that Up Next entry, dropping the ones before it |
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

## Sound effects

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/effects` | Registered sound effects: [{name, title, volume, duration_ms, size, source, created, updated, playing}] |
| `POST` | `/api/effects` | Register a sound effect (admins only). Send the audio as the raw body (Content-Type audio/* or application/octet-stream) with ?name=slug, or multipart/form-data with `name` and a `file` part, or JSON {name, url} to fetch it. wav, mp3, ogg or flac, max 25 MB and 120 s; converted once to 48 kHz stereo wav (mp3/ogg/flac need ffmpeg on the server). Optional title, volume (0-100, the default play volume) and overwrite. 409 exists if the name is taken |
| `GET` | `/api/effects/playing` | Effects playing right now: [{id, name, volume, slider_volume, volume_source, effective_volume, duck, started_at, elapsed_ms, duration_ms}] (volumes as in play) |
| `POST` | `/api/effects/stop` | Stop every playing effect (or only those called `name`). Music is not touched. Returns {stopped: n} |
| `GET` | `/api/effects/{name}` | One sound effect's metadata; 404 unknown_effect |
| `PATCH` | `/api/effects/{name}` | Body {name?, title?, volume?} (admins only): rename or change the default play volume (0-100) |
| `DELETE` | `/api/effects/{name}` | Delete a sound effect (admins only); stops it if it is playing |
| `POST` | `/api/effects/{name}/play` | Play a sound effect now, over whatever is playing (its own PipeWire stream; music is not paused). Returns at once with {id, name, volume, slider_volume, volume_source, effective_volume, duck, duration_ms, started_at}. Body/query optional: volume (0-100, default the effect's own), duck (bool: lower the other streams while it plays, to duck_level % of their volume, default 30). It plays at effective_volume = volume x slider_volume / 100. slider_volume is the level actually used: by default effects follow the music volume slider (/api/volume, volume_source "media"), so 100 matches the music; the slider is the last one known (kept through AirPlay, idle and restarts; 50 until one is seen). When an admin sets a fixed effects volume (/api/admin/effects-volume), slider_volume is that level and volume_source is "fixed". Plays may overlap. While quiet hours have the speakers locked, effects still play when the admin setting play_during_quiet_hours is on (the default, /api/admin/effects-volume): the outputs are unmuted just for the effect, quiet_hours is true in the response, and the lock, its idle clock and music are not touched. With the setting off they get 423 quiet_hours like music |

## System audio

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/system/volume` | Machine's output volume (PipeWire / PulseAudio / macOS), separate from Spotify's own volume |
| `POST` | `/api/system/volume` | Body {volume?: 0-100, delta?: ±n, muted?: bool} |
| `GET` | `/api/system/outputs` | Audio outputs (sinks) on this machine, e.g. the USB speakers (Linux) |
| `POST` | `/api/system/outputs` | Body {id}: make that output the default (Linux) |

## Admin

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/admin/system` | System health (admins only): {sampled_at, hostname, model, uptime_s, cpu {percent, cores: [%], count, freq_mhz, max_mhz}, load [1, 5, 15 min], temp_c, power {source: vcgencmd\|sysfs\|hwmon, raw, now {under_voltage, freq_capped, throttled, soft_temp_limit}, since_boot {same}, events (under-voltage kernel messages this boot), last_event_at}, memory {total, available, used, percent, swap_total, swap_used} (bytes), disk {path, total, used, free, percent}, network {interface, ip, ssid, bssid, signal_dbm, quality 0-100, bitrate_mbps, freq_mhz}, services [{name, unit, scope: user\|system, state, sub, since, enabled, restartable}], versions {commit, commit_short, subject, built_at, python, soloist, shairport_sync, kernel, os}, history [{t, cpu, temp}] (every 5 s, last 10 min)}. ?history=0 leaves out the history. Unknown values are null |
| `POST` | `/api/admin/services/{name}/restart` | Restart soloist, airplay or music-display (admins only) → {name, state}. Restarting soloist interrupts the music for a few seconds; restarting airplay disconnects the AirPlay sender |
| `GET` | `/api/admin/logs/{name}` | Recent journal lines of a service from the System list (admins only): ?lines= (default 200, max 1000) → {name, unit, lines: [str], error} |
| `GET` | `/api/admin/quiet-hours` | Quiet-hours settings and state (admins only): {settings {enabled, start: "21:00", end: "08:00", grace_min, source: admin\|env, env_window, updated_by, updated_at}, status (as GET /api/quiet-hours, plus override {kind: unlocked\|locked, until_ts, by})} |
| `PUT` | `/api/admin/quiet-hours` | Body {enabled?, start?: "HH:MM", end?: "HH:MM", grace_min?} (admins only): change the window at runtime, or {reset: true} to go back to the server default (QUIET_HOURS). Saved in the data dir and also used by the OS watchdog (quiet_hours.py sync, the AirPlay receiver's start check). Applies at once: enabling a window that has already started locks the speakers if nothing has played for the grace period |
| `POST` | `/api/admin/quiet-hours/override` | Body {action: unlock\|lock\|clear} (admins only). unlock: the speakers stay unlocked until the current (or next) window ends. lock: lock now until the window ends (409 outside the window). clear: back to the normal rules |
| `GET` | `/api/admin/effects-volume` | Sound effects settings (admins only): {mode: follow\|fixed, level, media_volume, play_during_quiet_hours, updated_by, updated_at}. follow (the default, "Same as media"): effects play at volume x the music slider / 100. fixed: at volume x level / 100, whatever the music volume. level is the fixed level (the music slider until one is set); media_volume is the music slider effects would follow. play_during_quiet_hours (default true): effects keep playing while quiet hours have the speakers locked (music stays refused); false refuses them with 423 |
| `PUT` | `/api/admin/effects-volume` | Body {mode?: follow\|fixed, level?: 0-100, play_during_quiet_hours?: bool} (admins only): change the sound effects settings. Saved in the data dir and used from the next play on. Switching to fixed without a level keeps the current music slider as the level. Returns the settings as GET |
| `GET` | `/api/admin/admins` | Admins (admins only): {admins: [{key, id, email, name, avatar, source: config\|admin, added_by, added, you}], known: [{id, name, avatar, email, admin, last_seen}] (everyone who has signed in)}. config admins come from SLACK_ADMINS and can't be removed here; API tokens are always admin |
| `POST` | `/api/admin/admins` | Body {id} (Slack user ID) or {email} (admins only): make someone an admin, saved in the data dir. 409 if they already are. Returns the same as GET |
| `GET` | `/api/admin/bans` | Banned people (admins only): {bans: [{key, id, email, name, reason, banned_by {id, name}, banned}]}. A banned person gets 403 on every API request and sign-in, including their personal API token, and the Slack bot ignores them |
| `POST` | `/api/admin/bans` | Body {id} (Slack user ID) or {email}, optional {reason} (admins only): ban someone, saved in the data dir. 409 if they already are or it's you. Returns the same as GET |
| `DELETE` | `/api/admin/bans/{key}` | Lift a ban (admins only); key from GET. Returns the same as GET |
| `DELETE` | `/api/admin/admins/{key}` | Remove an admin added here (admins only); key from GET. 409 for config admins and for removing yourself as the last admin. Returns the same as GET |
| `GET` | `/api/admin/update` | Update status (admins only): {configured, setup_hint, deployed {commit, short, subject, date, built_at}, latest {commit, short, subject, date} (origin/main), build {commit, short, built_at, ready} (the pi-build branch GitHub Actions publishes), behind, commits [{commit, short, subject, author, date}] newest first, changes {files, restarts, units, notes}, fetched_at, fetch_error, run {id, state: running\|succeeded\|rolled_back\|failed, started_at, finished_at, from, to, result, log [{t, msg, level}]}}. Fetches from GitHub if the last fetch is over 10 min old |
| `POST` | `/api/admin/update/check` | Fetch from GitHub now (admins only); returns the same as GET |
| `POST` | `/api/admin/update` | Update to the latest build (admins only). Runs in the background: stages the build, swaps it in, restarts music-api (and music-display if its files changed; Soloist and AirPlay keep playing), health-checks /api/status and rolls back if that fails. Poll GET for run.state and run.log; expect the API to drop for a few seconds. 409 if already up to date or an update is running |

Admins only (403 for everyone else): API tokens, and Slack users listed in `SLACK_ADMINS` or added on the admin page (`<data-dir>/admins.json`). The web app's admin page (`/admin`, account menu > Admin) is built on these.

## Other

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/airplay` | AirPlay session: {active, state: playing\|paused, sender, track {name, artists, album, artwork, duration_ms}, position_ms, duration_ms, started_at, resume_spotify} or {active: false}. Also folded into /api/status as source "airplay" while a session is on |
| `GET` | `/api/airplay/artwork` | Cover art the AirPlay sender sent for the current song (bytes); 404 if none |
| `POST` | `/api/airplay/stop` | End the AirPlay session (restarts the receiver, which disconnects the sender; it can reconnect a few seconds later). Spotify then resumes if it was playing when AirPlay took over. 409 airplay_inactive if there's none |
| `GET` | `/api/quiet-hours` | Quiet hours: {enabled, window: "21:00-08:00", phase: open\|grace\|locked, locked, idle_since, locks_at, until: "08:00", until_ts, starts_at, grace_s}. After the window starts the speakers lock once nothing has played for grace_s seconds; while locked, play/resume/skip are refused with 423 {"error": "quiet_hours", "until"} |
| `POST` | `/api/playpause` | Toggle play/pause (the AirPlay sender's, during AirPlay) |
| `GET` | `/api/app/me` | Who's signed in: {id, name, avatar, admin, kind: slack\|token}. API tokens show as Admin |
| `GET` | `/api/app/token` | Your personal API token {token, created, docs}: same permissions as you; created on first request |
| `POST` | `/api/app/token/regenerate` | Replace your personal API token; the old one stops working immediately |
| `GET` | `/api/app/playlists` | Playlists shown in the web app (the account's own are hidden), newest first, with created_by, source_url, can_edit |
| `POST` | `/api/app/playlists` | Body {name, description?}: create a playlist credited to you |
| `POST` | `/api/app/playlists/import` | Body {url}: copy a Spotify, Apple Music or YouTube playlist/song link into a new playlist → {playlist, imported, total, truncated, source, unmatched: [{name, artists}]}. Album links are added to the Library as albums instead → {kind: "album", album: {...}}, unless {as: "playlist"} (e.g. an Apple Music or YouTube album with no Spotify match) copies its songs into a playlist |
| `POST` | `/api/app/playlists/{id}/duplicate` | Body {name?}: copy a playlist's tracks into a new playlist credited to you → the new playlist |
| `POST` | `/api/resolve` | Body {url}: a Spotify, Apple Music or YouTube song/album/playlist link → {source, kind, name, subtitle, artwork, url, spotify_uri, tracks: [{name, artists, album, duration_ms, artwork, uri}], total, matched, truncated} |
| `GET` | `/api/app/playlists/{id}` | One app playlist |
| `PATCH` | `/api/app/playlists/{id}` | Body {name?, description?} (creator or admin) |
| `DELETE` | `/api/app/playlists/{id}` | Delete (creator or admin) |
| `GET` | `/api/app/library` | ?kind=all\|playlists\|albums&sort=recent\|name\|creator (default all, recent). → {items: [...]}: playlists as in /api/app/playlists plus kind "playlist", albums as in POST /api/app/library/albums with kind "album"  |
| `POST` | `/api/app/library/albums` | Body {url \| uri}: a Spotify album URI/link or an Apple Music or YouTube Music album link with a Spotify match (else 422: use Import as playlist). Admins may also pass {added_by: {id, name, avatar}, added: ISO time}. Idempotent (existing → "already": true). → {kind: "album", id, uri, name, artists: [{uri, name}], artwork, total, year, duration_ms, added_by, added, source_url, can_edit} |
| `GET` | `/api/app/library/albums/{id}` | A library album plus "tracks": every track as a compact item |
| `DELETE` | `/api/app/library/albums/{id}` | Remove an album from the Library (whoever added it, or an admin) → {removed: "spotify:album:..."} |
| `GET` | `/api/app/library/songs` | ?q=&sort=recent\|title\|artist\|album&offset=&limit= (default 100, max 500). Every distinct track across the Library's playlists and albums → {items: [{...track item, sources: [{kind: playlist\|album, id, name}], added}], total} |
| `POST` | `/api/app/library/songs/play` | Body {uri, sort?, q?}: play the songs list (same q/sort as GET /api/app/library/songs) as a queue of up to 100 tracks starting at uri; credited to you |
| `GET` | `/api` | This list as JSON: a bare array of `{method, path, doc}` (no `result` envelope) |
| `GET` | `/api/events` | Server-sent events: `status` (every 1 s with Soloist, 2 s with connect, while anyone listens), `track`, `queue` (Soloist only), `sleep`, `activity`, `error`. Use `?token=` with `EventSource` |
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
| `POST` | `/slack/commands` | Slack `/music` slash command (checked by the Slack signing secret) |
| `POST` | `/slack/interactions` | Slack button clicks (signing secret) |
| `POST` | `/slack/events` | Slack Events API: URL verification and `link_shared` unfurls (signing secret) |
| `OPTIONS` | `*` | CORS preflight (`Access-Control-Allow-Origin: *` on every response) |
