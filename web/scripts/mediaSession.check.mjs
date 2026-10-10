import { chromium } from 'playwright-core'

const url = process.argv[2] ?? 'http://localhost:5173/?mock'
const executablePath = process.env.CHROME ?? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const browser = await chromium.launch({ executablePath })
const page = await browser.newPage()
await page.addInitScript(() => {
  window.__handlers = {}
  const set = navigator.mediaSession.setActionHandler.bind(navigator.mediaSession)
  navigator.mediaSession.setActionHandler = (action, handler) => {
    window.__handlers[action] = handler
    return set(action, handler)
  }
  const play = HTMLMediaElement.prototype.play
  HTMLMediaElement.prototype.play = function () {
    window.__silent = this
    return play.call(this)
  }
})

const failures = []
const check = (name, ok, detail = '') => {
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}${detail ? ` (${detail})` : ''}`)
  if (!ok) failures.push(name)
}
const calls = () => page.evaluate(() => window.__mockCalls.map((c) => ({ method: c.method, path: c.path, origin: c.origin })))
const clearCalls = () => page.evaluate(() => (window.__mockCalls.length = 0))
const lab = (fn, arg) => page.evaluate(([f, a]) => window.__mockLab[f](a), [fn, arg])
const wait = (ms) => page.waitForTimeout(ms)

await page.goto(url)
await wait(2000)
await page.getByRole('button', { name: 'Account' }).click()
await page.getByRole('switch', { name: 'Sync to Now Playing' }).click()
await page.keyboard.press('Escape')
await wait(2000)
check('sync enabled', await page.evaluate(() => !!window.__silent && !window.__silent.paused))

await clearCalls()
await lab('next')
await wait(2500)
await lab('pause')
await wait(2500)
await lab('resume')
await wait(2500)
await lab('seek', 200000)
await wait(2500)
await page.evaluate(() => {
  window.__silent.currentTime = 5
})
await wait(1500)
const passive = await calls()
check('lab-side track change, pause, resume, drift and element seeks make no API calls', passive.length === 0, JSON.stringify(passive))

await lab('pause')
await page.waitForFunction(() => window.__silent.paused, null, { timeout: 5000 })
await wait(1200)
await clearCalls()
await lab('resume')
await page.waitForFunction(() => !window.__silent.paused, null, { timeout: 5000 })
await page.evaluate(() => window.__handlers.pause({ action: 'pause' }))
await wait(400)
const echo = await calls()
check('pause echoed right after our own play() is ignored', echo.length === 0, JSON.stringify(echo))

await wait(1200)
await page.evaluate(() => window.__handlers.play({ action: 'play' }))
await wait(400)
const redundant = await calls()
check('play while the lab is already playing sends nothing', redundant.length === 0, JSON.stringify(redundant))

await page.evaluate(() => {
  window.__handlers.nexttrack({ action: 'nexttrack' })
  window.__handlers.nexttrack({ action: 'nexttrack' })
})
await wait(500)
const skips = (await calls()).filter((c) => c.path === '/api/next')
check('double nexttrack is rate-limited to one call', skips.length === 1, JSON.stringify(skips))
check('media-session calls are tagged with their origin', skips[0]?.origin === 'media-session:nexttrack', skips[0]?.origin ?? 'none')

await wait(1500)
await clearCalls()
await page.locator('footer').getByRole('button', { name: 'Next', exact: true }).click()
await wait(500)
const ui = (await calls()).filter((c) => c.path === '/api/next')
check('UI calls are tagged ui', ui.length === 1 && ui[0].origin === 'ui', JSON.stringify(ui))

await browser.close()
process.exit(failures.length ? 1 : 0)
