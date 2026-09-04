import { useCallback, useEffect, useRef, useState } from 'react'

export interface ResourceState<T> {
  data: T | null
  loading: boolean
  error: unknown | null
}

export function useResource<T>(load: () => Promise<T>) {
  const generation = useRef(0)
  const mounted = useRef(false)
  const [state, setState] = useState<ResourceState<T>>({
    data: null,
    loading: true,
    error: null,
  })

  const retry = useCallback(async () => {
    const current = ++generation.current
    setState((previous) => ({ ...previous, loading: true, error: null }))
    try {
      const data = await load()
      if (mounted.current && current === generation.current) {
        setState({ data, loading: false, error: null })
      }
    } catch (error) {
      if (mounted.current && current === generation.current) {
        setState((previous) => ({ ...previous, loading: false, error }))
      }
    }
  }, [load])

  useEffect(() => {
    mounted.current = true
    void retry()
    return () => {
      mounted.current = false
      generation.current += 1
    }
  }, [retry])

  return { ...state, retry }
}
