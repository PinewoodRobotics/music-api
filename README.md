# Music API v2 (Spotify)

HTTP API and web remote for Spotify. It's the successor to the Music.app-only v1.
Python 3.9+ stdlib only, no `pip install`. Runs on headless Linux (Raspberry Pi) and macOS.

```
python3 server.py --client-id <spotify app client id>     # http://127.0.0.1:8765/
python3 server.py auth                                     # log in to the Web API from a terminal / over SSH
python3 server.py --host 0.0.0.0 --token SECRET            # LAN access
```

`GET /api` lists every endpoint. See [API.md](API.md) for the full reference (regenerate it with `python3 gen_api_md.py > API.md`).

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
4. **This server's own token**, as in v1. Use `--token` / `$MUSIC_API_TOKEN` / `--public`. It's required off-localhost.
   Soloist's WebSocket has *no* auth at all, so it stays bound to `127.0.0.1`, and this server is the only door in.

### Web API limits (development-mode apps, 2026 rules)

- The app owner needs Premium. A new app gets at most 5 users (add them under *User Management*).
- Search returns at most 10 results per type per page. Page with `offset`.
- Playlist **items** only come back for playlists you own or collaborate on. Any playlist can still be *played* by URI.
- Removed by Spotify, so not available here: browse/categories, new releases, artist top tracks, recommendations,
  audio features, related artists, popularity, batch lookups.
- Saving and removing goes through the generic `/me/library` (`PUT/DELETE /api/library {uris}`, max 40 per call).

## Raspberry Pi notes

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

## Beyond Spotify's APIs

- `GET /api/lyrics`: synced lyrics from [LRCLIB](https://lrclib.net), with the current line index.
- `POST /api/sleep {minutes, fade}`: sleep timer that fades out, pauses and restores the volume.
- `GET/POST /api/system/volume`, `/api/system/outputs`: the machine's own mixer (PipeWire / PulseAudio / macOS).
- `GET /api/artwork?proxy=1`: cover image bytes, for e-ink and other microcontroller clients that can't do HTTPS.
- `ANY /api/spotify/{path}`: raw Web API passthrough using the stored login, for anything not wrapped yet.

## Status

Built and smoke-tested on macOS. Tested so far: the route table, auth flow plumbing, LRCLIB lyrics and the macOS mixer.
Not yet tested: the Web API calls (they need a login) and the Soloist backend (it needs a Linux box with an API key).
