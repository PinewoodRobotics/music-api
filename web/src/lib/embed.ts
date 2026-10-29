const KEY = 'embed'

function readEmbed(): string | null {
  try {
    const url = new URL(location.href)
    const fromUrl = url.searchParams.get(KEY)
    if (fromUrl === null) return sessionStorage.getItem(KEY)
    if (fromUrl) sessionStorage.setItem(KEY, fromUrl)
    else sessionStorage.removeItem(KEY)
    url.searchParams.delete(KEY)
    history.replaceState(history.state, '', url.pathname + url.search + url.hash)
    return fromUrl || null
  } catch {
    return null
  }
}

/** Set by ?embed=<host> when another app frames this one (e.g. the FMS touch panel), which brings its own player bar. */
export const embed = readEmbed()

if (embed) document.documentElement.dataset.embed = embed
