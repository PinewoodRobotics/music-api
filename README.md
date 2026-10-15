# Music API v2 (Spotify)

HTTP API and web remote for Spotify. It's the successor to the Music.app-only v1.
Python 3.9+ stdlib only, no `pip install`. Runs on headless Linux (Raspberry Pi) and macOS.

```
python3 server.py --client-id <spotify app client id>     # http://127.0.0.1:8765/
python3 server.py auth                                     # log in to the Web API from a terminal / over SSH
python3 server.py --host 0.0.0.0 --token SECRET            # LAN access
```

`GET /api` lists every endpoint. See [API.md](API.md) for the full reference (regenerate it with `python3 gen_api_md.py > API.md`).
Production lives at https://music.pinewoodrobotics.org: a Raspberry Pi 3 B+ running Soloist into USB speakers, behind a
Cloudflare tunnel (see [Raspberry Pi setup](#raspberry-pi-setup-soloist)).

## Docs

All of these are served without a token, so you can point an LLM agent straight at them:

- [`/llms.txt`](https://music.pinewoodrobotics.org/llms.txt): short index in the [llms.txt](https://llmstxt.org) format.
- [`/llms-full.txt`](https://music.pinewoodrobotics.org/llms-full.txt) (also `/LLMS.md`): the whole reference in one file, written so an agent can drive the API with no other context. Endpoints, response shapes, curl examples, workflows, limits.
- [`/API.md`](https://music.pinewoodrobotics.org/API.md): one table row per endpoint, generated from the route docstrings.
- `/README.md`: this file.

`llms.txt` and `llms-full.txt` are written by hand. Update them when you add or change a route.

## How it fits together

```
 phone / web remote / scripts ──HTTP+SSE──► server.py (this) ──┬─ WebSocket (127.0.0.1) ─► Spotify Soloist ─► PipeWire ─► USB speakers
                                                               ├─ HTTPS ─► Spotify Web API  (search, library, playlists,   ▲
                                                               │                             history, any Connect device) │
 iPhone / Mac ──AirPlay──► shairport-sync ────────────────────────────────────────────────────────────────────────────────────┘
                                   ├─ metadata pipe ─► server.py (now playing, pauses Spotify while AirPlay plays)
                                   └─ D-Bus RemoteControl ◄─ server.py (play/pause/next/previous back to the sender)
```

There are two playback backends, chosen with `--backend auto|soloist|connect`:

| | `soloist` (Linux) | `connect` (anywhere) |
|---|---|---|
| Plays audio | Locally, through Spotify Soloist | On any Spotify Connect device: Spotify desktop app, phone, speaker, librespot |
| Control path | Soloist's local WebSocket: push events, no polling, no rate limits | Web API `/me/player` (polled every 2 s while someone is listening) |
| Needs | Soloist API key (Premium) and a one-time pairing | Web API login, Premium on the listening account |
| Queue | Previous + up to 80 upcoming, each tagged context / queue / autoplay | Upcoming only |

`auto` picks Soloist if it's running (or has ever run) on this machine, otherwise `connect`.
Anything the Soloist socket can't do falls back to the Web API, targeted at the Soloist device.
That covers starting a playlist at a given track, playing an artist, playing a list of URIs, and listing other devices.

## Authentication: five separate layers

1. **Soloist API key.** Generate it at developer.spotify.com/dashboard → *Spotify Soloist API Key*.
   The generating account must have Premium. It's passed on every start (`--api-key`), so the
   [run script](deploy/run-soloist.sh) reads it from `~/.config/music-api/env` (mode 600). It's per person: don't share it or commit it.
2. **Soloist's Connect session.** There's no username or password. Start Soloist, open the Spotify app on the
   same network, and pick the device. Soloist stores that session in its data directory
   (`~/.local/share/soloist`) and restores it on restart. Free accounts can connect once it's set up.
   Re-pair with `soloist --pair`.
3. **Web API (OAuth Authorization Code + PKCE).** Needed for search, library, playlists, history and the `connect` backend.
   Create an app at developer.spotify.com/dashboard. Add `http://127.0.0.1:8765/auth/callback` (or your tunnel's
   `https://…/auth/callback`) as a Redirect URI and start the server with `--client-id`. No client secret is involved.
   Then either:
   - open `/auth/login` in a browser, or
   - on a headless box, run `python3 server.py auth` over SSH, or open `/auth/login` from your phone. Spotify will redirect
     to `127.0.0.1`, which won't load on the phone. Paste that URL into the box on the page.
   Tokens (with a refresh token) go to `~/.local/share/music-api/spotify-tokens.json` (mode 600) and refresh automatically.
4. **This server's own API tokens.** Send `Authorization: Bearer <token>` (or `?token=` for `EventSource`, `<img>` and links).
   Required off-localhost, with `--public` (even from localhost), and as soon as any token exists. See [API tokens](#api-tokens).
   Soloist's WebSocket has *no* auth at all, so it stays bound to `127.0.0.1`, and this server is the only door in.
5. **Sign in with Slack** for the web app. See [Web app accounts](#web-app-accounts-sign-in-with-slack).

### API tokens

Tokens have no scopes: every token can do everything, including managing tokens.

- `GET /api/tokens` lists them: `id`, `name`, `prefix` (the first few characters, to recognize one), `created`, `last_used`, and `current` (the one you're calling with).
- `POST /api/tokens {name?}` creates one (`mapi_…`). The response is the only time the token itself is shown.
- `DELETE /api/tokens/{id}` revokes one immediately. Any token can revoke any token, including itself. Revoking the last one is refused (409), so you can't lock yourself out.

Only SHA-256 hashes are stored, in `<data-dir>/api-tokens.json` (mode 600; data dir defaults to `~/.local/share/music-api`).
On the first start that requires auth, `<data-dir>/token` is imported as "v1 token" if it exists (that's where the v1 token was migrated),
then deleted, so only its hash remains. If there's no such file either, a token is generated and written to `<data-dir>/token` (mode 600) for you to read.
`--token` / `$MUSIC_API_TOKEN` still works as an extra static token. It isn't listed and can't be revoked through the API.
To hand someone the web remote, create a token and send them `https://…/?token=<token>`; the page remembers it.

### Web app accounts (Sign in with Slack)

People sign in to the web app with their Slack account in the pinewoodrobotics workspace and appear under their Slack
display name. The session is an HttpOnly cookie (30 days, stored hashed in `<data-dir>/sessions.json`).
API tokens keep working and act as **Admin**. Slack users are admins if their user ID or email is in `SLACK_ADMINS` (comma-separated) or an admin added them on the [admin page](#admin-page).
Everyone signed in with Slack also gets a personal API token (`mapu_…`, account menu → API) that acts as them; regenerating it revokes the old one.
Every play and queue action is credited to whoever did it (`credit` on `/api/status`, `added_by` on the queue), saved in `<data-dir>/credits.json` and shown in the web app and the Slack feed.
Non-admins can control playback, search, queue, lyrics and the app's playlists, but get 403 on tokens, the Spotify login,
the raw passthrough, the account's library/history and hidden playlists. Cookie-authenticated writes from another origin are refused.

The app shows every playlist in the Spotify account *except* those listed in `~/.config/music-api/hidden-playlists.json`
(`{"playlists": ["<id>" or {"id", "name"}, ...]}`, kept only on the Pi). Playlists created or imported in the app are
credited to whoever made them (`<data-dir>/app-playlists.json`); only they or an admin can rename or delete them, and
anyone can add or remove tracks. Importing copies a *public* playlist into a new private playlist on the account. Spotify
only exposes the first 100 tracks of playlists the account doesn't own (through the public embed page), so that's the cap.

Apple Music and YouTube links are read for titles, artists and lengths only (`links.py`, `yt.py`) and matched to Spotify songs; nothing plays from them.
YouTube / YouTube Music songs, albums and public or unlisted playlists (up to 500 songs) work from `youtube.com`, `music.youtube.com`,
`youtu.be`, Shorts and embed links. Metadata comes from YouTube Music's public InnerTube endpoints (the client version lives in
`yt.CLIENT_VERSION`; bump it if YouTube starts rejecting requests) with oEmbed as the fallback for single videos. Plain uploads
get their "Artist - Title (Official Video)" noise cleaned up first. Private lists, mixes and channel links are refused.

Setup: create a Slack app from this manifest at api.slack.com/apps, install it to the workspace, and put
`SLACK_CLIENT_ID`, `SLACK_CLIENT_SECRET`, `SLACK_BOT_TOKEN` (`xoxb-…`) and `SLACK_REDIRECT_URI` in `~/.config/music-api/env`.
The bot token is used for `users.info` (display names), `auth.test` (the workspace ID sign-ins must match), and the Slack bot below.

**Sign in with Google.** An alternative for `@pinewood.edu` accounts (`GET /auth/google/login`, callback `/auth/google/callback`, `GET /auth/methods` returns
`{"slack": bool, "google": bool}`). The Google email is mapped to the Slack user with the same email (`users.lookupByEmail`), so the session, name, avatar,
admin rights and personal token are identical to signing in with Slack. Accounts that aren't verified, not in the allowed domain, or not in the Slack workspace are refused.
1. Google Cloud console > APIs & Services > Credentials > Create credentials > OAuth client ID > Web application.
   Authorized redirect URI: `https://music.pinewoodrobotics.org/auth/google/callback`.
2. OAuth consent screen: user type **Internal** if available (Workspace), scopes `openid email profile`.
3. In `~/.config/music-api/env` set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` and optionally `GOOGLE_REDIRECT_URI`
   (default `<MUSIC_API_URL>/auth/google/callback`, else `http://127.0.0.1:<port>/auth/google/callback`) and `GOOGLE_ALLOWED_DOMAIN` (default `pinewood.edu`).
4. Add the bot scope `users:read.email` to the Slack app and reinstall it (without it Google sign-in shows "isn't fully set up yet").

**Slack bot ("Robotics Music").** Set `SLACK_SIGNING_SECRET` (Basic Information > Signing Secret) and invite the bot to the channel
(`SLACK_MUSIC_CHANNEL`, default #music). Without the secret the bot stays off and the server starts normally.
- *Live feed:* every track change posts one "Now playing" message (art, title, who queued it, the next 3 songs with art, Play/Pause, Skip, More Controls).
  It is edited on pause/resume and queue changes (at most every 5 s) and shrinks to a compact "Played" line when the track changes.
- `/music <query>` searches (Add to queue / Play buttons), `/music now`, `/music queue`, `/music play|pause|skip`, `/music help`.
  Pasting a Spotify link after `/music` works too. Skips, pauses and plays are announced in the channel with who did them.
- Tracks queued from Slack are credited to that person, so the web app's Up Next shows "Added by".
- Spotify, Apple Music and YouTube / YouTube Music song, album and playlist links shared in Slack (or after `/music`) unfurl with Add to queue / Play / Import as playlist buttons.
- A Spotify, Apple Music or YouTube link posted in the music channel gets one threaded reply (also sent to the channel) with a card per link (up to 3): Play now, Queue, and Add to Library / Import to Library. Clicks update that same message with who did what.
- `/slack/*` requests are verified with the signing secret (v0 HMAC, 5 minute window) and only accepted from the workspace.

```yaml
display_information:
  name: Robotics Music
  description: So Musical!!
features:
  bot_user:
    display_name: Robotics Music
    always_online: true
  slash_commands:
    - command: /music
      url: https://music.pinewoodrobotics.org/slack/commands
      description: Search, queue and control the lab speakers
      usage_hint: "[song, artist, link | now | queue | play | pause | skip | help]"
      should_escape: false
  unfurl_domains:
    - open.spotify.com
    - music.apple.com
    - youtube.com
    - music.youtube.com
    - youtu.be
oauth_config:
  redirect_urls:
    - https://music.pinewoodrobotics.org/auth/slack/callback
  scopes:
    user: [openid, profile, email]
    bot: [users:read, chat:write, commands, links:read, links:write]
settings:
  event_subscriptions:
    request_url: https://music.pinewoodrobotics.org/slack/events
    bot_events: [link_shared]
  interactivity:
    is_enabled: true
    request_url: https://music.pinewoodrobotics.org/slack/interactions
  org_deploy_enabled: false
  socket_mode_enabled: false
  token_rotation_enabled: false
```
After changing scopes, reinstall the app to the workspace so the bot token picks them up.
For an app that already exists, add `youtube.com`, `music.youtube.com` and `youtu.be` under *Event Subscriptions > App Unfurl Domains* in the Slack app settings (the manifest above only applies to new apps); without them YouTube links won't unfurl or get channel cards.

### Web API limits (development-mode apps, 2026 rules)

- The app owner needs Premium. A new app gets at most 5 users (add them under *User Management*).
- Search returns at most 10 results per type per page. Page with `offset`.
- Playlist **items** only come back for playlists you own or collaborate on. Any playlist can still be *played* by URI.
- Removed by Spotify, so not available here: browse/categories, new releases, artist top tracks, recommendations,
  audio features, related artists, popularity, batch lookups.
- Saving and removing goes through the generic `/me/library` (`PUT/DELETE /api/library {uris}`, max 40 per call).

## Raspberry Pi setup (Soloist)

Tested target: Pi 3 B+ or newer (incl. Zero 2 W) on **Raspberry Pi OS Lite 64-bit**, USB speakers. No cooling needed
for audio; use a proper 5 V / 2.5 A supply (`vcgencmd get_throttled` should print `0x0`).

1. Copy this repo to the Pi (e.g. `scp -r music-api-v2 pi@music.local:`), then on the Pi:
   `cd music-api-v2 && sh deploy/install-linux.sh`
2. Create a Soloist API key (developer.spotify.com/dashboard → Spotify Soloist API Key, Premium account) and fill in
   `~/.config/music-api/env`: `SOLOIST_API_KEY`, `DEVICE_NAME`, `SPOTIFY_CLIENT_ID`.
3. Pick the output: `wpctl status`, find the USB speakers under *Sinks*, then `wpctl set-default <id>`
   (or put the node name in `SOLOIST_PIPEWIRE_DEVICE`).
4. `systemctl --user start soloist music-api`, then in the Spotify app on the same Wi-Fi pick `DEVICE_NAME` once
   to pair Soloist. `soloist ctl status` should now say logged in. Use the desktop or mobile app; the web player only
   lists devices that are already logged in. Pairing relies on mDNS, so the app must be on the Pi's subnet; see
   [Pairing from another subnet](#pairing-from-another-subnet) if it isn't.
5. Log in to the Web API over SSH: `python3 ~/.local/share/music-api-v2/server.py auth --client-id <id>` and paste the
   redirected URL (`auth` doesn't read the env file, hence `--client-id`).
   It doesn't open a port, so the service can keep running; afterwards `systemctl --user restart music-api` so it picks up the login.
6. Your first API token: `cat ~/.local/share/music-api/token`. Test with
   `curl -H "Authorization: Bearer <token>" http://music.local:8765/api/status`; it should say `"backend": "soloist"`.
   Then manage tokens with `/api/tokens` and delete that file.
7. Logs: `journalctl --user-unit soloist --user-unit music-api -f` (Pi OS keeps the journal in RAM, so `journalctl --user` finds nothing).

### Cloudflare tunnel

`music.pinewoodrobotics.org` is a named tunnel run by a system `cloudflared` service on the Pi.
The API service runs with `--public`, because tunnelled requests arrive from `127.0.0.1` and would otherwise skip the token check.
To set it up again (install `cloudflared` from [pkg.cloudflare.com](https://pkg.cloudflare.com/index.html) first):

```
cloudflared tunnel login                                    # pick the pinewoodrobotics.org zone in the browser
cloudflared tunnel create music-api
cloudflared tunnel route dns -f music-api music.pinewoodrobotics.org
sudo mkdir -p /etc/cloudflared && sudo cp ~/.cloudflared/<tunnel-id>.json /etc/cloudflared/
sudo tee /etc/cloudflared/config.yml <<EOF
tunnel: <tunnel-id>
credentials-file: /etc/cloudflared/<tunnel-id>.json
ingress:
  - hostname: music.pinewoodrobotics.org
    service: http://127.0.0.1:8765
  - service: http_status:404
EOF
sudo cloudflared service install
```

Logs: `journalctl -u cloudflared -f`.

### Pairing from another subnet

Spotify apps find unpaired Connect devices over mDNS, which doesn't cross routers. If your computer is on a different
subnet from the Pi but can reach it by IP, relay Soloist's pairing port through the computer and advertise it there
(macOS shown; get the port and path with `avahi-browse -rt _spotify-connect._tcp` on the Pi):

```
ssh -N -g -L 0.0.0.0:<port>:127.0.0.1:<port> ubuntu@<pi-ip> &
dns-sd -R "PEARL Speakers" _spotify-connect._tcp local <port> Stack=SP VERSION=1.0 CPath=/zc
```

Restart the Spotify desktop app, pick the device, then stop both commands. Advertising the Pi's own address
(`dns-sd -P … <pi-ip>`) doesn't work: the app ignores devices that resolve to another subnet.

### Raspberry Pi notes

- **Pi Zero W / Pi 1 (ARMv6) can't run Soloist.** Spotify only ships armv7 (`arm32`), arm64 and x86_64 builds.
  You have two options:
  - Get a **Pi Zero 2 W**. It's the same size and price class, and its armv7/arm64 CPU runs the official builds.
  - On the Zero W, run the API with `--backend connect` and use a community **librespot** build for ARMv6 as the speaker.
    librespot is unofficial and not supported by Spotify. Raspotify dropped ARMv6, so you'd build librespot yourself
    with its armv6hf Docker image.
- **USB speakers.** Soloist outputs through PipeWire (falling back to PulseAudio). Find the speakers with `wpctl status`.
  Then either set `SOLOIST_PIPEWIRE_DEVICE` in the env file, or make them the default with `POST /api/system/outputs {id}`.
- **Install.** On the Pi, run `sh deploy/install-linux.sh`. It installs PipeWire, enables lingering so user services run
  without a login, installs the AirPlay receiver (the distro `shairport-sync` package), installs systemd user units for Soloist, the API, AirPlay, the
  quiet-hours timer and a daily Soloist update, and creates `~/.config/music-api/env`.
- **Build expiry.** Soloist builds expire 90 days after they're built (exit code 10).
  [`deploy/update-soloist.sh`](deploy/update-soloist.sh) runs daily and pulls the current build from Spotify's CDN.
  Spotify asks that the binary not be redistributed, so it's never committed here.

### Quiet hours

From `QUIET_HOURS` (env file or `--quiet-hours`, default `21:00-08:00`, local time, may wrap midnight, `off` disables it):

- When the window starts nothing is cut off. Whatever is playing (Spotify or AirPlay) keeps going and people can keep
  playing, skipping and starting new AirPlay sessions. That's the **grace** phase.
- Once no audio has come from any source for 5 continuous minutes (counted from the window start if it was already
  quiet, so an idle evening locks at 21:05), the speakers **lock** until the window ends: play, resume, skip, jump and
  transfer-with-play are refused with `423 {"error": "quiet_hours", "until": "08:00", "message": ...}` from every
  route, the Slack bot and the raw `/api/spotify/me/player/...` passthrough. Pause, volume, search, playlists, the
  Library and queue editing keep working. The AirPlay receiver stops advertising and every output sink is muted.
  At the end of the window both are restored (the mute state each sink had before).
- `GET /api/quiet-hours` and `status.quiet_hours` report `{window, phase: open|grace|locked, idle_since, locks_at, until}`.
- The lock and the idle clock live in `<data-dir>/quiet-hours.json`, so restarts and reboots keep them. A reboot during
  the window comes up locked if it was locked, otherwise in grace with the persisted idle clock (so a box that was idle
  locks right away, and one that had been playing locks 5 minutes after boot unless something plays).
- OS-level backstop, independent of the server: `quiet-hours.timer` runs `quiet_hours.py sync` every minute, which
  applies the lock (receiver stopped, sinks muted) and undoes it in the morning. If the server's heartbeat in that
  file is older than 150 s it also judges idleness itself from PipeWire sink activity (`pactl list short sinks`,
  RUNNING = audio) and locks on its own. `airplay.service` has `quiet_hours.py receiver-allowed` as its
  `ExecCondition`, so it can't come back while locked (boot, crash restart or a manual start).
- Set the Pi's timezone (`sudo timedatectl set-timezone America/Los_Angeles`); the installer warns if it's UTC.
- Admins can change the window and grace period at runtime on the admin page. That's saved in
  `<data-dir>/quiet-hours-settings.json`, takes precedence over `QUIET_HOURS` (Reset goes back to it) and is read by the
  watchdog and the receiver's `ExecCondition` too. Admins can also skip tonight's quiet hours (unlock until the window
  ends) or lock right away during the window.

### Admin page

Admins (`SLACK_ADMINS`, people added on the page itself in `<data-dir>/admins.json`, and API tokens) get **Admin** in
the account menu (`/admin`), backed by `/api/admin/*` (403 for everyone else):

- **System:** CPU (overall and per core) and temperature with 10 minute sparklines, load, under-voltage and throttling
  (now and since boot, from the firmware's `get_throttled` via sysfs or `vcgencmd`, else the `rpi_volt` hwmon alarm and
  kernel log), memory, disk, Wi-Fi, service states and versions. A sampler thread reads `/proc/stat` and the thermal zone
  every 5 s; subprocesses (`systemctl`, `iw`, `journalctl`) are cached, so polling every 2 s is cheap on a Pi 3.
- **Quiet hours:** see above. **Sound effects:** "Same as media" (effects follow the music slider) or a separate
  effects volume, see [Sound effects](#sound-effects). **Admins:** add people who have signed in, or by Slack ID / email; config admins can't be
  removed here, and nobody can remove themselves as the last admin.
- **Updates:** compares the deployed commit (`BUILD.json`) with GitHub and updates without stopping the music, below.
- **Services:** restart Soloist, AirPlay or the display (with a confirmation) and read each unit's recent journal.

#### Updates from GitHub

`.github/workflows/pi-build.yml` runs the Python tests on every push to `main`, builds `web/dist` and force-pushes the
deployable tree (what `deploy-pi.sh` copies, plus `BUILD.json`) to the `pi-build` branch, using the workflow's own token.
On the Pi, `updater.py` keeps a bare clone (`~/.local/share/music-api-repo.git`) that fetches `main` and `pi-build`
with a read-only deploy key (`~/.ssh/music-api-deploy`). An update stages `pi-build` in `music-api-v2.new`, swaps it in
(the old tree stays as `music-api-v2.prev`), installs changed unit files that are already installed (`daemon-reload`),
restarts music-api only if Python files changed and music-display only if its files changed, then checks `/api/status`.
If that fails it swaps back and restarts again. Soloist and the AirPlay receiver are never restarted, and anything that
needs sudo (apt packages, `install-airplay.sh`) is listed as a note instead of being run. It runs as a transient
`systemd-run --user` unit so it survives the music-api restart; progress goes to `<data-dir>/update.json`.

One-time setup on the Pi: `python3 ~/.local/share/music-api-v2/updater.py setup` creates the key and the bare repo and
prints the public key. Add it on GitHub (repo Settings > Deploy keys, read-only), then `python3 updater.py status`.
`python3 updater.py update` does the same as the button. `deploy/deploy-pi.sh` keeps working and writes `BUILD.json` too.

### AirPlay receiver

The Pi also shows up as an AirPlay speaker named `AIRPLAY_NAME` (default "PEARL Speakers"), using classic AirPlay (no
multi-room, no AirPlay 2). AirPlay completely overrides Spotify:

- A session starting pauses Soloist (track, position and queue stay put) and remembers whether it was playing.
- While it lasts, `/api/status` shows the AirPlay song (`source: "airplay"`, title, artist, album, art at
  `/api/airplay/artwork`, progress, `airplay.sender`). Queue and library editing still work. AirPlay doesn't carry
  the sender's queue, so there's no Up Next for it.
- Play, pause, play/pause, next and previous (`/api/play` with no body, `/api/pause`, `/api/playpause`, `/api/next`,
  `/api/previous`, the web app and the Slack bot) control the AirPlay sender instead of Spotify. They go through
  shairport-sync's D-Bus `RemoteControl` interface, which finds the sender's DACP service and uses its Active-Remote
  token. If the sender has no remote control (some apps and Android senders) they fail with
  `409 airplay_remote_unavailable`. Everything else in Spotify transport (play a track, seek, jump, transfer) is refused
  with `409 {"error": "airplay_active", "sender": ...}`.
- The Slack #music feed posts AirPlay songs too once they have a title, artist and cover art (no art usually means a video
  or podcast, which isn't posted): same card, credited to the sender's device name, no Up next. The cover is served
  without a token at `/airplay-art/<12-hex content hash>` (the last 8 covers are kept) so Slack can fetch it.
- When it ends (the sender stops or disconnects, or someone presses Stop AirPlay / `POST /api/airplay/stop`, which
  restarts the receiver to drop the sender, who can reconnect a few seconds later), Spotify resumes right where it
  left off if it was playing before, and stays paused otherwise. It doesn't resume if quiet hours have locked.

How it's installed (`deploy/install-airplay.sh`, run by `install-linux.sh`; `NO_AIRPLAY=1` skips it): the distro
`shairport-sync` package (Ubuntu 24.04: 3.3.8, Debian 13: 4.3.7) is classic AirPlay and is built with PulseAudio
output, the metadata pipe, D-Bus/MPRIS and MQTT. The script installs it, disables the package's system service,
checks those features, and removes the AirPlay 2 build (NQPTP, `/usr/local/bin/shairport-sync`) an earlier version of
the script installed. shairport-sync runs as the `airplay.service` user unit (it has to, to reach the user's
PipeWire and session bus), with [`deploy/shairport-sync.conf`](deploy/shairport-sync.conf): PulseAudio output,
metadata and cover art to `/tmp/shairport-sync-metadata`, D-Bus on the session bus. The server reads that pipe
(`--airplay-pipe`); a missing pipe (macOS, receiver not installed) is fine, and shairport-sync restarts are picked up.
Remote control needs `busctl` (systemd) and `dbus-user-session`. A server restart mid-song loses the session until the
next song starts (classic AirPlay has no heartbeat to rejoin it).
Logs: `journalctl --user-unit airplay -f`.

### Sound effects

Register short clips by name and play them over whatever else is playing, e.g. for the practice field's match timer (`/api/effects`; reference in [API.md](API.md) and `llms-full.txt`).

- `POST /api/effects?name=match-start` with the audio as the body (`Content-Type: audio/wav`, mp3, ogg or flac, or multipart, or JSON `{name, url}`) registers a clip; `GET/PATCH/DELETE /api/effects/{name}` read, rename and delete it. Registering and deleting are admin-only.
- `POST /api/effects/{name}/play {volume?, duck?, duck_level?}` returns immediately. `POST /api/effects/stop` stops every playing effect.
- Effects follow the music volume slider (Spotify's volume, `/api/volume`): a play runs at `volume` x slider / 100, reported as `slider_volume` and `effective_volume` (`volume_source: "media"`). The slider is read from Soloist's local state, or the last value seen in a status or volume change (connect mode, AirPlay, idle), never from the Web API at play time. It is persisted in `<data-dir>/effects/slider.json`; until one has been seen it is 50.
- Admins can unhook effects from the music volume (Admin > Sound effects: uncheck **Same as media**, then set **Sound effects volume**; `/api/admin/effects-volume`). Plays then run at `volume` x that level / 100 and report it as `slider_volume` with `volume_source: "fixed"`. Saved in `<data-dir>/effects/volume.json`; applies to the next play.
- Playing is one `pw-play` process per play: its own PipeWire stream, mixed with Spotify and AirPlay, which keep playing untouched. Plays may overlap (16 at most). Nothing is transcoded at play time: at registration ffmpeg converts the upload to 48 kHz stereo 16-bit WAV (PipeWire's rate) and it is stored as `<data-dir>/effects/<name>.wav` with `index.json`. Without ffmpeg only PCM WAV uploads are accepted, as they are.
- `duck: true` lowers the other PipeWire streams (`pactl set-sink-input-volume`) to `duck_level` % (default 30) while the effect plays and restores them when the last ducking effect ends, or at the next server start if it died mid-duck. Streams that begin during the duck aren't lowered, and the music's own volume setting is not touched.
- Quiet hours: effects are refused with `423 quiet_hours` while the speakers are locked, exactly like play, and allowed during the grace phase and outside the window. There is no force override, because the lock mutes every sink at the OS level. Managing and stopping effects always works.
- The Pi needs `pw-play` (`pipewire-bin`) and `ffmpeg`; `install-linux.sh` and `deploy-pi.sh` install them if missing. Plays are not written to the activity feed.

### HDMI now-playing display

`display/now_playing_display.py` draws a now-playing screen (blurred artwork background, big cover, title, progress, "Playing Next") straight into `/dev/fb0` on a Pi with no desktop. It needs only `python3-pil` and `fonts-inter`, follows `/api/events`, and redraws the progress bar at most every 2 s.

- AirPlay sessions show the sender's art and song with "AirPlay from <sender>". As soon as nothing is playing (paused, stopped, quiet-hours locked, logged out) it draws black and powers the HDMI output down with the `FBIOBLANK` ioctl on `/dev/fb0` (the DRM connector goes to DPMS Off so the monitor enters standby; the `video` group can do this, no udev rule or root needed). Anything playing wakes it at once and redraws the full scene; a 1.5 s debounce keeps track changes from flickering.
- Future option: cutting USB power to the screen with `uhubctl` isn't viable on a Pi 3 B+ because its USB ports switch together and would also cut the USB speakers; it would need a per-port-switchable hub or a smart plug.
- It reads the framebuffer size at runtime, so it works at any resolution (16 or 32 bpp). For 1080p add `video=HDMI-A-1:1920x1080@60` to `/boot/firmware/cmdline.txt`; `vt.global_cursor_default=0 consoleblank=0 quiet logo.nologo` keeps the text console quiet.
- `install-linux.sh` disables `getty@tty1`, lets the `video` group hide the tty1 cursor, silences console kernel messages, and enables the `music-display` user unit. Create its token once: `POST /api/tokens {"name": "pi display"}` into `~/.config/music-api/display-token` (mode 600).
- Preview without a framebuffer: `python3 display/now_playing_display.py --render-png /tmp/shot.png --size 1920x1080`.

## Running on macOS (launchd + Cloudflare tunnel)

This is how it ran in production on the lab Mac before moving to the Pi (the agent is saved in
[`deploy/macos/`](deploy/macos/org.pinewoodrobotics.music-api.plist); copy it to `~/Library/LaunchAgents/` and
`launchctl bootstrap gui/$(id -u) <plist>` to bring it back). Two launchd agents, both `RunAtLoad` + `KeepAlive`:

- `~/Library/LaunchAgents/org.pinewoodrobotics.music-api.plist` runs `python3 server.py --public --client-id <id>`
  from `~/Developer/music-api-v2`. Output goes to `server.log` in the repo directory (gitignored).
  On a Mac there's no Soloist, so `auto` picks the `connect` backend: play on the Spotify desktop app or any other Connect device.
- `org.pinewoodrobotics.music-api-tunnel` runs `cloudflared` with `~/.cloudflared/music-api.yml`, which maps
  `music.pinewoodrobotics.org` to `http://127.0.0.1:8765`.

```
launchctl kickstart -k gui/$(id -u)/org.pinewoodrobotics.music-api    # restart after a code change
tail -f ~/Developer/music-api-v2/server.log
```

`--public` makes every request need a token, because tunnelled requests arrive from `127.0.0.1` too.
For Web API login through the public URL, add `https://music.pinewoodrobotics.org/auth/callback` as a Redirect URI
in the Spotify app and add `--redirect-uri` with that URL to the plist. Otherwise use the paste flow.
v1 (Music.app) lived in `~/Developer/music-api` and is retired.

## Beyond Spotify's APIs

- `GET /api/lyrics`: synced lyrics from [LRCLIB](https://lrclib.net), with the current line index.
- `POST /api/sleep {minutes, fade}`: sleep timer that fades out, pauses and restores the volume.
- `GET/POST /api/system/volume`, `/api/system/outputs`: the machine's own mixer (PipeWire / PulseAudio / macOS).
- `GET /api/artwork?proxy=1`: cover image bytes, for e-ink and other microcontroller clients that can't do HTTPS.
- `ANY /api/spotify/{path}`: raw Web API passthrough using the stored login, for anything not wrapped yet.
- `GET /api/airplay`, `GET /api/airplay/artwork`, `POST /api/airplay/stop`: the AirPlay receiver (see above).
- `GET /api/quiet-hours`: the quiet-hours window and lock state.
- `/api/effects`: named sound effects played over the music (see [Sound effects](#sound-effects)).

## Status

- Tested against a real Spotify account (via the `connect` backend): every read endpoint, playlist create/edit/add/
  reorder/remove/delete, library save/remove, lyrics, tokens, the public URL through the tunnel.
- Soloist backend running on a Pi 3 B+ (Soloist 1.3.9.5): pairing, status, play/pause, position, and audio out through
  the tunnel. `soloist ctl trace` shows the raw events to compare against `soloist.py`.
