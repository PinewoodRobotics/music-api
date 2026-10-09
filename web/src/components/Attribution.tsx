import type { Person } from '../lib/api'
import { SOURCE_LABELS, sourceOfUrl } from '../lib/links'
import { Avatar } from './Avatar'
import { SourceIcon } from './SourceIcon'

type Props = {
  person: Pick<Person, 'name' | 'avatar'> | null | undefined
  sourceUrl?: string | null
  className?: string
  avatarClass?: string
  linkSource?: boolean
}

export function Attribution({ person, sourceUrl, className = '', avatarClass = 'size-4 text-[9px]', linkSource }: Props) {
  const source = sourceOfUrl(sourceUrl)
  if (!person?.name && !source) return null
  const icon = source && <SourceIcon source={source} className="size-3.5 shrink-0" />
  return (
    <span className={`inline-flex min-w-0 max-w-full items-center gap-1.5 ${className}`}>
      {person?.name && <Avatar person={person} className={avatarClass} />}
      {person?.name && <span className="truncate">{person.name}</span>}
      {icon &&
        (linkSource && sourceUrl ? (
          <a href={sourceUrl} target="_blank" rel="noreferrer" title={`Imported from ${SOURCE_LABELS[source]}`} className="shrink-0 opacity-80 hover:opacity-100">
            {icon}
          </a>
        ) : (
          <span title={`Imported from ${SOURCE_LABELS[source]}`} className="shrink-0">
            {icon}
          </span>
        ))}
    </span>
  )
}
