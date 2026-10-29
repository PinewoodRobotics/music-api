const SF: Record<string, string> = {
  search: '\u{1002AB}',
  library: '\u{100B12}',
  'library-big': '\u{100B13}',
  'list-music': '\u{10046C}',
  play: '\u{100284}',
  pause: '\u{100286}',
  'skip-forward': '\u{100290}',
  'skip-back': '\u{10028E}',
  shuffle: '\u{10029D}',
  repeat: '\u{10029E}',
  'repeat-1': '\u{10029F}',
  x: '\u{100184}',
  plus: '\u{10017C}',
  check: '\u{100185}',
  'chevron-left': '\u{100189}',
  'chevron-right': '\u{10018A}',
  'chevron-down': '\u{100188}',
  'chevron-up': '\u{100187}',
  'arrow-down-up': '\u{10012C}',
  'layout-grid': '\u{1001F7}',
  list: '\u{1002F2}',
  ellipsis: '\u{100360}',
  'clock-3': '\u{10042B}',
  'disc-3': '\u{1008B8}',
  'user-round': '\u{100269}',
  users: '\u{10026B}',
  'music-2': '\u{10046A}',
  'list-plus': '\u{1002F8}',
  'list-end': '\u{101640}',
  download: '\u{100204}',
  'trash-2': '\u{100211}',
  radio: '\u{100319}',
  speaker: '\u{10074E}',
  volume: '\u{1002A1}',
  'volume-1': '\u{1002A5}',
  'volume-2': '\u{1002A7}',
  'volume-x': '\u{1002A3}',
  airplay: '\u{100462}',
  moon: '\u{1001BA}',
  lock: '\u{1003A1}',
  'link-2': '\u{100263}',
  'circle-alert': '\u{10005E}',
  'triangle-alert': '\u{1001FE}',
  info: '\u{100174}',
  'cloud-off': '\u{10030F}',
  'refresh-cw': '\u{100148}',
  'rotate-cw': '\u{100148}',
  'rotate-ccw': '\u{100149}',
  'circle-check': '\u{100063}',
}

const SVG = 'http://www.w3.org/2000/svg'

function glyphFor(svg: SVGSVGElement) {
  for (const c of svg.classList) if (c.startsWith('lucide-') && SF[c.slice(7)]) return SF[c.slice(7)]
  return null
}

// lucide-react re-renders only its own path children, so an extra <text> survives updates; a changed icon
// is a new <svg> and gets swapped again by the observer.
function swap(svg: SVGSVGElement) {
  const glyph = glyphFor(svg)
  const current = svg.querySelector(':scope > text.sf-glyph')
  if (!glyph) {
    current?.remove()
    svg.classList.remove('sf')
    return
  }
  if (current?.textContent === glyph) return
  const text = current ?? document.createElementNS(SVG, 'text')
  text.setAttribute('class', 'sf-glyph')
  text.setAttribute('x', '12')
  text.setAttribute('y', '12')
  text.textContent = glyph
  if (!current) svg.appendChild(text)
  svg.classList.add('sf')
}

function scan(root: ParentNode) {
  root.querySelectorAll<SVGSVGElement>('svg.lucide').forEach(swap)
}

export function swapIcons() {
  scan(document)
  new MutationObserver((records) => {
    for (const r of records) {
      if (r.type === 'attributes') {
        if (r.target instanceof SVGSVGElement && r.target.classList.contains('lucide')) swap(r.target)
        continue
      }
      r.addedNodes.forEach((n) => {
        if (n instanceof SVGSVGElement && n.classList.contains('lucide')) swap(n)
        else if (n instanceof Element) scan(n)
      })
    }
  }).observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['class'] })
}
