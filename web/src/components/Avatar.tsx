import type { Person } from '../lib/api'

export function Avatar({ person, className = 'size-4' }: { person: Pick<Person, 'name' | 'avatar'>; className?: string }) {
  if (person.avatar) return <img src={person.avatar} alt="" className={`${className} shrink-0 rounded-full bg-raised object-cover`} />
  return (
    <span className={`${className} grid shrink-0 place-items-center rounded-full bg-white/20 text-[0.6em] font-bold uppercase text-fg`}>
      {person.name.replace('@', '').slice(0, 1)}
    </span>
  )
}
