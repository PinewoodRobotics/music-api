"""Regenerate API.md from the route docstrings:  python3 gen_api_md.py > API.md"""
import inspect
import server

SECTIONS = [("Playback", "/api/status /api/now-playing /api/artwork /api/play /api/pause /api/next /api/previous /api/back /api/seek /api/volume /api/shuffle /api/repeat /api/lyrics /api/sleep"),
            ("Queue & devices", "/api/queue /api/devices /api/backend"),
            ("Catalog", "/api/search /api/tracks /api/albums /api/artists /api/episodes /api/shows /api/audiobooks /api/chapters"),
            ("Playlists", "/api/playlists"),
            ("Library & history", "/api/library /api/recent /api/top /api/me"),
            ("System audio", "/api/system")]

print("# Music API v2 reference\n")
print("Every JSON response is `{\"result\": ...}` on success or `{\"error\": \"...\"}` with a 4xx/5xx status.")
print("When a token is set, send `Authorization: Bearer <token>` (or `?token=` for `EventSource` / `<img>`).")
print("IDs can be bare Spotify IDs; bodies that take `uri`/`uris` also accept `spotify:` URIs and open.spotify.com links.\n")
seen = set()
for title, prefixes in SECTIONS:
    rows = [r for r in server.ROUTES if any(r[2] == p or r[2].startswith(p + "/") or r[2].startswith(p + "-") for p in prefixes.split())]
    print(f"## {title}\n\n| Method | Path | Notes |\n|---|---|---|")
    for m, _, path, doc, fn in rows:
        if (m, path) in seen:
            continue
        seen.add((m, path))
        print(f"| `{m}` | `{path}` | {inspect.cleandoc(doc).replace(chr(10), ' ').replace('|', '\\|')} |")
    print()
rest = [r for r in server.ROUTES if (r[0], r[2]) not in seen]
print("## Other\n\n| Method | Path | Notes |\n|---|---|---|")
for m, _, path, doc, fn in rest:
    print(f"| `{m}` | `{path}` | {inspect.cleandoc(doc).replace(chr(10), ' ').replace('|', '\\|')} |")
print("| `GET` | `/api/events` | Server-sent events: `status` (1/s while anyone listens), `track`, `queue`, `sleep`, `error` |")
print("| `ANY` | `/api/spotify/{path}` | Raw Spotify Web API passthrough with your login, e.g. `GET /api/spotify/me/player/devices` |")
print("\n## Auth (Web API login)\n\n| Method | Path | Notes |\n|---|---|---|")
print("| `GET` | `/auth` | Login status, scopes, redirect URI |")
print("| `GET` | `/auth/login` | Login page; `?redirect=1` goes straight to Spotify |")
print("| `GET` | `/auth/callback` | OAuth redirect target (checked by PKCE state, no token needed) |")
print("| `POST` | `/auth/paste` | Body `{url}`: finish login by pasting the redirected URL (headless boxes) |")
print("| `POST` | `/auth/logout` | Forget the Web API tokens |")
