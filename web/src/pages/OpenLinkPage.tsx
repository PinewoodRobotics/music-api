import { detectLink } from '../lib/links'
import { Message } from './Message'
import { LinkResult } from './search/LinkResult'

export function OpenLinkPage({ url }: { url: string }) {
  const link = detectLink(url)
  if (!link) return <Message title="This link isn't supported" body="Open a Spotify, Apple Music or YouTube link." />
  return (
    <div className="pb-12 pt-2">
      <LinkResult url={url} link={link} />
    </div>
  )
}
