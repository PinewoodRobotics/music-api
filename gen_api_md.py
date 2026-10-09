"""Regenerate API.md from the route docstrings:  python3 gen_api_md.py > API.md"""
import inspect
import server

BASE = "https://music-api.pinewoodrobotics.org"
SECTIONS = [("Playback", "/api/status /api/now-playing /api/artwork /api/play /api/pause /api/next /api/previous /api/back /api/seek /api/volume /api/shuffle /api/repeat /api/lyrics /api/sleep"),
            ("Queue & devices", "/api/queue /api/devices /api/backend"),
            ("Catalog", "/api/search /api/tracks /api/albums /api/artists /api/episodes /api/shows /api/audiobooks /api/chapters"),
            ("Playlists", "/api/playlists"),
            ("Library & history", "/api/library /api/recent /api/top /api/me"),
            ("Tokens", "/api/tokens"),
            ("System audio", "/api/system")]


def doc(d):
    return inspect.cleandoc(d).replace("\n", " ").replace("|", "\\|")


def row(m, path, notes):
    print(f"| `{m}` | `{path}` | {notes} |")


HEAD = "| Method | Path | Notes |\n|---|---|---|"

print("# Music API v2 reference\n")
print(f"Base URL: `{BASE}` (or `http://127.0.0.1:8765` on the machine itself). "
      f"For a self-contained guide written for LLM agents, see [llms-full.txt]({BASE}/llms-full.txt).\n")
print("Every JSON response is `{\"result\": ...}` on success or `{\"error\": \"...\"}` with a 4xx/5xx status "
      "(exceptions: `GET /api` returns a bare array; `/api/artwork` returns a redirect or image bytes; `/auth/login` returns HTML).")
print("Send an API token as `Authorization: Bearer <token>` (or `?token=` for `EventSource` / `<img>` / browser links). "
      "A token is required as soon as any token exists, when started with `--public`, or when listening beyond localhost.")
print("Path `{id}`s are bare 22-character Spotify IDs. `uri`/`uris`/`context` fields take `spotify:` URIs or open.spotify.com links; "
      "`/api/play` `uris`, `/api/queue` and `offset` also accept bare IDs (as tracks).\n")
seen = set()
for title, prefixes in SECTIONS:
    rows = [r for r in server.ROUTES if any(r[2] == p or r[2].startswith(p + "/") or r[2].startswith(p + "-") for p in prefixes.split())]
    print(f"## {title}\n\n{HEAD}")
    for m, _, path, d, fn in rows:
        if (m, path) in seen:
            continue
        seen.add((m, path))
        row(m, path, doc(d))
    if title == "Tokens":
        print("\nTokens have no scopes: any token can do everything, including creating and revoking tokens. "
              "Only SHA-256 hashes are stored (`<data-dir>/api-tokens.json`, mode 600). New tokens look like `mapi_…`. "
              "A `--token` / `$MUSIC_API_TOKEN` static token also works but isn't listed and can't be revoked here. "
              "Revoking the last listed token is refused (409) unless a static token is configured.")
    print()
rest = [r for r in server.ROUTES if (r[0], r[2]) not in seen]
print(f"## Other\n\n{HEAD}")
for m, _, path, d, fn in rest:
    row(m, path, doc(d))
row("GET", "/api", "This list as JSON: a bare array of `{method, path, doc}` (no `result` envelope)")
row("GET", "/api/events", "Server-sent events: `status` (every 1 s with Soloist, 2 s with connect, while anyone listens), "
    "`track`, `queue` (Soloist only), `sleep`, `error`. Use `?token=` with `EventSource`")
row("ANY", "/api/spotify/{path}", "Raw Spotify Web API passthrough with your login, e.g. `GET /api/spotify/me/player/devices`")
print(f"\n## Auth (Web API login)\n\n{HEAD}")
row("GET", "/auth", "Login status, scopes, redirect URI")
row("GET", "/auth/login", "Login page; `?redirect=1` goes straight to Spotify")
row("GET", "/auth/callback", "OAuth redirect target (checked by PKCE state, no token needed)")
row("POST", "/auth/paste", "Body `{url}`: finish login by pasting the redirected URL (headless boxes)")
row("POST", "/auth/logout", "Forget the Web API tokens")
print(f"\n## No token needed\n\n{HEAD}")
row("GET", "/", "Web remote (open `/?token=…` once; the page remembers it)")
row("GET", "/llms.txt", "llms.txt index for LLM agents")
row("GET", "/llms-full.txt", "Complete agent-oriented reference in one file")
row("GET", "/LLMS.md", "Same content as `/llms-full.txt`, served as Markdown")
row("GET", "/API.md", "This file")
row("GET", "/README.md", "Overview, setup and deployment")
row("GET", "/auth/callback", "OAuth redirect target")
row("OPTIONS", "*", "CORS preflight (`Access-Control-Allow-Origin: *` on every response)")
