import { useEffect } from 'react'

const PUBLIC_ORIGIN = 'https://kivou.eu'

/** Page-specific metadata without adding a client-side head dependency.
 * Existing tags are updated in place and restored when the route unmounts. */
export function PublicPageMeta({
  title,
  description,
  canonicalPath,
}: {
  title: string
  description: string
  canonicalPath: string
}) {
  useEffect(() => {
    const previousTitle = document.title
    const descriptionState = ensureHeadElement<HTMLMetaElement>('meta[name="description"]', () => {
      const element = document.createElement('meta')
      element.name = 'description'
      return element
    })
    const canonicalState = ensureHeadElement<HTMLLinkElement>('link[rel="canonical"]', () => {
      const element = document.createElement('link')
      element.rel = 'canonical'
      return element
    })
    const descriptionTag = descriptionState.element
    const canonicalTag = canonicalState.element
    const previousDescription = descriptionTag.getAttribute('content')
    const previousCanonical = canonicalTag.getAttribute('href')

    document.title = title
    descriptionTag.content = description
    canonicalTag.href = `${PUBLIC_ORIGIN}${canonicalPath}`

    return () => {
      document.title = previousTitle
      restoreElement(descriptionTag, descriptionState.created, 'content', previousDescription)
      restoreElement(canonicalTag, canonicalState.created, 'href', previousCanonical)
    }
  }, [canonicalPath, description, title])

  return null
}

function ensureHeadElement<T extends HTMLElement>(selector: string, create: () => T) {
  const existing = document.head.querySelector<T>(selector)
  if (existing) return { element: existing, created: false }
  const element = create()
  document.head.append(element)
  return { element, created: true }
}

function restoreElement(
  element: HTMLElement,
  created: boolean,
  name: string,
  value: string | null,
) {
  if (created) {
    element.remove()
    return
  }
  if (value === null) element.removeAttribute(name)
  else element.setAttribute(name, value)
}
