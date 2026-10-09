import { readFileSync } from 'node:fs'
import { pickTopResult } from '../src/pages/search/topResult.ts'

const dir = process.argv[2]
const cases: [string, string][] = [
  ['seal', 'artist Seal'],
  ['daft punk', 'artist Daft Punk'],
  ['c418', 'artist C418'],
  ['discovery', 'album Discovery'],
  ['one more time', 'track One More Time'],
  ['lofi', 'artist Lofi Girl'],
  ['kiss from a rose', 'track Kiss from a Rose'],
  ['minecraft', '?'],
]
let failed = 0
for (const [q, expected] of cases) {
  const data = JSON.parse(readFileSync(`${dir}/${q.replace(/ /g, '_')}.json`, 'utf8')).result
  const top = pickTopResult(q, data)
  const by = top && 'artists' in top.item ? ` (${top.item.artists?.map((a) => a.name).join(', ')})` : ''
  const got = top ? `${top.kind} ${top.item.name}` : 'none'
  const ok = expected === '?' || got.toLowerCase() === expected.toLowerCase()
  if (!ok) failed++
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${q.padEnd(17)} -> ${got}${by}${ok ? '' : `   expected ${expected}`}`)
}
process.exit(failed ? 1 : 0)
