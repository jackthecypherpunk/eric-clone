import { memo, useMemo } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import type { DocCard } from '@/lib/api'
import { cn } from '@/lib/utils'
import { docLabel, useOpenSource } from './source-viewer'

const CITE = /\[\[\s*((?:tg|blog):[^\]\s]+)\s*\]\]/g
const CITE_HREF = '#cite='

/** Turns the agent's [[doc-id]] markers into numbered markdown links we render as citation chips. */
export function numberCitations(text: string): { markdown: string; order: string[] } {
  const order: string[] = []
  const markdown = text.replace(CITE, (_, id: string) => {
    let n = order.indexOf(id)
    if (n === -1) n = order.push(id) - 1
    return ` [${n + 1}](${CITE_HREF}${encodeURIComponent(id)})`
  })
  return { markdown, order }
}

function CitationChip({ id, n, doc }: { id: string; n: string; doc?: DocCard }) {
  const open = useOpenSource()
  const chip = (
    <button
      onClick={() => open(id)}
      className="mx-0.5 inline-flex h-5 min-w-5 -translate-y-0.5 items-center justify-center rounded-md bg-cite px-1.5 align-middle text-[11px] font-semibold text-cite-foreground no-underline transition-opacity hover:opacity-80"
    >
      {n}
    </button>
  )
  return (
    <Tooltip>
      <TooltipTrigger asChild>{chip}</TooltipTrigger>
      <TooltipContent className="max-w-sm">
        {doc ? (
          <div className="space-y-1">
            <p className="font-medium">
              {docLabel(doc)} · {doc.date}
            </p>
            <p dir="auto" className="line-clamp-4 opacity-80">
              {doc.text}
            </p>
          </div>
        ) : (
          <span>{id}</span>
        )}
      </TooltipContent>
    </Tooltip>
  )
}

export const AnswerMarkdown = memo(function AnswerMarkdown({
  text,
  docs,
  streaming,
}: {
  text: string
  docs: Map<string, DocCard>
  streaming?: boolean
}) {
  const { markdown } = useMemo(() => numberCitations(text), [text])
  const components = useMemo<Components>(
    () => ({
      a: ({ href, children }) => {
        if (href?.startsWith(CITE_HREF)) {
          const id = decodeURIComponent(href.slice(CITE_HREF.length))
          return <CitationChip id={id} n={String(children)} doc={docs.get(id)} />
        }
        return (
          <a href={href} target="_blank" rel="noreferrer">
            {children}
          </a>
        )
      },
      p: ({ children }) => <p dir="auto">{children}</p>,
      ul: ({ children }) => <ul dir="auto">{children}</ul>,
      ol: ({ children }) => <ol dir="auto">{children}</ol>,
      li: ({ children }) => <li dir="auto">{children}</li>,
      blockquote: ({ children }) => <blockquote dir="auto">{children}</blockquote>,
      h1: ({ children }) => <h3 dir="auto">{children}</h3>,
      h2: ({ children }) => <h3 dir="auto">{children}</h3>,
      h3: ({ children }) => <h3 dir="auto">{children}</h3>,
    }),
    [docs],
  )
  return (
    <div className={cn('prose-answer text-[15px]', streaming && 'is-streaming')}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {markdown}
      </ReactMarkdown>
    </div>
  )
})
