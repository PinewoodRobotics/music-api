import { useEffect, useState, type DependencyList } from 'react'

export type Async<T> = { data: T | undefined; error: unknown; loading: boolean }

export function useAsync<T>(load: () => Promise<T>, deps: DependencyList): Async<T> & { setData: (d: T) => void } {
  const [state, setState] = useState<Async<T>>({ data: undefined, error: null, loading: true })
  useEffect(() => {
    let live = true
    setState({ data: undefined, error: null, loading: true })
    load().then(
      (data) => live && setState({ data, error: null, loading: false }),
      (error) => live && setState({ data: undefined, error, loading: false }),
    )
    return () => {
      live = false
    }
  }, deps)
  return { ...state, setData: (data) => setState({ data, error: null, loading: false }) }
}
