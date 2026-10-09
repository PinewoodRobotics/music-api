export function focusSearch() {
  const input = document.querySelector<HTMLInputElement>('[data-search-input]')
  if (!input) return false
  input.focus({ preventScroll: true })
  input.select()
  return true
}
