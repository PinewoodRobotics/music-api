# Music API v2 (Spotify)

HTTP API and web remote for Spotify. It's the successor to the Music.app-only v1.
Python 3.9+ stdlib only, no `pip install`. Runs on headless Linux (Raspberry Pi) and macOS.

```
python3 server.py --client-id <spotify app client id>     # http://127.0.0.1:8765/
python3 server.py auth                                     # log in to the Web API from a terminal / over SSH
python3 server.py --host 0.0.0.0 --token SECRET            # LAN access
```

`GET /api` lists every endpoint. See [API.md](API.md) for the full reference (regenerate it with `python3 gen_api_md.py > API.md`).
Production lives at https://music-api.pinewoodrobotics.org (see [Running on macOS](#running-on-macos-launchd--cloudflare-tunnel)).

## Docs

All of these are served without a token, so you can point an LLM agent straight at them:

- [`/llms.txt`](https://music-api.pinewoodrobotics.org/llms.txt): short index in the [llms.txt](https://llmstxt.org) format.
- [`/llms-full.txt`](https://music-api.pinewoodrobotics.org/llms-full.txt) (also `/LLMS.md`): the whole reference in one file, written so an agent can drive the API with no other context. Endpoints, response shapes, curl examples, workflows, limits.
- [`/API.md`](https://music-api.pinewoodrobotics.org/API.md): one table row per endpoint, generated from the route docstrings.
- `/README.md`: this file.

`llms.txt` and `llms-full.txt` are written by hand. Update them when you add or change a route.

## How it fits together

```
 phone / web remote / scripts ──HTTP+SSE──► server.py (this) ──┬─ WebSocket (127.0.0.1) ─► Spotify Soloist ─► PipeWire ─► USB speakers
                                                               └─ HTTPS ─► Spotify Web API  (search, library, playlists,
                                                                                             history, any Connect device)
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

## Authentication: four separate layers

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
   to pair Soloist. `soloist ctl status` should now say logged in.
5. Log in to the Web API over SSH: `python3 ~/.local/share/music-api-v2/server.py auth` and paste the redirected URL.
   It doesn't open a port, so the service can keep running; afterwards `systemctl --user restart music-api` so it picks up the login.
6. Your first API token: `cat ~/.local/share/music-api/token`. Test with
   `curl -H "Authorization: Bearer <token>" http://music.local:8765/api/status`; it should say `"backend": "soloist"`.
   Then manage tokens with `/api/tokens` and delete that file.
7. Logs: `journalctl --user -u soloist -u music-api -f`.

To put `music-api.pinewoodrobotics.org` on the Pi instead of a Mac, install `cloudflared` there, copy
`~/.cloudflared/music-api.yml` and the tunnel's credentials JSON, and run it as a service. Then stop the tunnel on the Mac.

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
  without a login, installs systemd user units for Soloist, the API and a daily Soloist update, and creates `~/.config/music-api/env`.
- **Build expiry.** Soloist builds expire 90 days after they're built (exit code 10).
  [`deploy/update-soloist.sh`](deploy/update-soloist.sh) runs daily and pulls the current build from Spotify's CDN.
  Spotify asks that the binary not be redistributed, so it's never committed here.

## Running on macOS (launchd + Cloudflare tunnel)

This is how it ran in production on the lab Mac before moving to the Pi (the agent is saved in
[`deploy/macos/`](deploy/macos/org.pinewoodrobotics.music-api.plist); copy it to `~/Library/LaunchAgents/` and
`launchctl bootstrap gui/$(id -u) <plist>` to bring it back). Two launchd agents, both `RunAtLoad` + `KeepAlive`:

- `~/Library/LaunchAgents/org.pinewoodrobotics.music-api.plist` runs `python3 server.py --public --client-id <id>`
  from `~/Developer/music-api-v2`. Output goes to `server.log` in the repo directory (gitignored).
  On a Mac there's no Soloist, so `auto` picks the `connect` backend: play on the Spotify desktop app or any other Connect device.
- `org.pinewoodrobotics.music-api-tunnel` runs `cloudflared` with `~/.cloudflared/music-api.yml`, which maps
  `music-api.pinewoodrobotics.org` to `http://127.0.0.1:8765`.

```
launchctl kickstart -k gui/$(id -u)/org.pinewoodrobotics.music-api    # restart after a code change
tail -f ~/Developer/music-api-v2/server.log
```

`--public` makes every request need a token, because tunnelled requests arrive from `127.0.0.1` too.
For Web API login through the public URL, add `https://music-api.pinewoodrobotics.org/auth/callback` as a Redirect URI
in the Spotify app and add `--redirect-uri` with that URL to the plist. Otherwise use the paste flow.
v1 (Music.app) lived in `~/Developer/music-api` and is retired.

## Beyond Spotify's APIs

- `GET /api/lyrics`: synced lyrics from [LRCLIB](https://lrclib.net), with the current line index.
- `POST /api/sleep {minutes, fade}`: sleep timer that fades out, pauses and restores the volume.
- `GET/POST /api/system/volume`, `/api/system/outputs`: the machine's own mixer (PipeWire / PulseAudio / macOS).
- `GET /api/artwork?proxy=1`: cover image bytes, for e-ink and other microcontroller clients that can't do HTTPS.
- `ANY /api/spotify/{path}`: raw Web API passthrough using the stored login, for anything not wrapped yet.

## Status

- Tested against a real Spotify account (via the `connect` backend): every read endpoint, playlist create/edit/add/
  reorder/remove/delete, library save/remove, lyrics, tokens, the public URL through the tunnel.
- Not yet tested: playback control on a live device, and the Soloist backend end to end (needs the Pi + API key).
  The WebSocket client follows Soloist's published API reference but hasn't talked to a real Soloist yet; if something's
  off, `soloist ctl trace` shows the raw events to compare against `soloist.py`.
