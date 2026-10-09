import { useState, type ReactNode } from 'react'
import { CardGrid, Section } from '../../components/MediaCard'

export function ShowAll({ expanded, onToggle }: { expanded: boolean; onToggle: () => void }) {
  return (
    <button type="button" onClick={onToggle} className="text-sm font-semibold text-dim hover:text-fg hover:underline">
      {expanded ? 'Show less' : 'Show all'}
    </button>
  )
}

export function CardSection({ title, cards }: { title: string; cards: ReactNode[] }) {
  const [expanded, setExpanded] = useState(false)
  if (!cards.length) return null
  return (
    <Section title={title} action={cards.length > 5 && <ShowAll expanded={expanded} onToggle={() => setExpanded((e) => !e)} />}>
      {expanded ? (
        <CardGrid>{cards}</CardGrid>
      ) : (
        <div className="no-scrollbar -mx-1 flex snap-x overflow-x-auto px-1 [&>*]:w-[184px] [&>*]:shrink-0 [&>*]:snap-start max-sm:[&>*]:w-[150px]">
          {cards}
        </div>
      )}
    </Section>
  )
}
