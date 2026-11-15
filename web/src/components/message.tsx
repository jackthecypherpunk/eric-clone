import { useMemo, useState } from 'react'
import { Check, Copy, FileText, Info, TriangleAlert } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { AgentId } from '@/lib/agents'
import { api, type DocCard } from '@/lib/api'
import type { Message } from '@/lib/conversations'
import { AgentIcon } from './agent-picker'
import { AnswerMarkdown } from './answer-markdown'
import { ReasoningBlock, ToolCallCard } from './tool-call'

export function UserMessage({ message }: { message: Message }) {
  const images = message.attachments?.filter((a) => a.kind === 'image') ?? []
  const docs = message.attachments?.filter((a) => a.kind !== 'image') ?? []
  return (
    <div className="flex flex-col items-end gap-2">
      {images.length > 0 && (
        <div className="flex max-w-[85%] flex-wrap justify-end gap-2">
          {images.map((a) => (
            <a key={a.id} href={api.imageUrl(a.id)} target="_blank" rel="noreferrer" title={a.name}>
              <img src={api.imageUrl(a.id)} alt={a.name} className="max-h-48 max-w-60 rounded-xl border object-cover" />
            </a>
          ))}
        </div>
      )}
      {docs.length > 0 && (
        <div className="flex max-w-[85%] flex-wrap justify-end gap-2">
          {docs.map((a) => (
            <div key={a.id} className="flex min-w-0 items-center gap-2 rounded-lg border bg-muted/40 px-2.5 py-1.5 text-xs">
              <FileText className="size-4 shrink-0 text-muted-foreground" />
              <span className="truncate font-medium">{a.name}</span>
              {a.pages ? <span className="shrink-0 text-muted-foreground">{a.pages} p.</span> : null}
            </div>
          ))}
        </div>
      )}
      {message.content && (
        <div dir="auto" className="max-w-[85%] rounded-2xl rounded-ee-md bg-secondary px-4 py-2.5 text-[15px] leading-7 break-words whitespace-pre-wrap">
          {message.content}
        </div>
      )}
    </div>
  )
}

export function AssistantMessage({ message, agent }: { message: Message; agent: AgentId }) {
  const parts = useMemo(() => message.parts ?? [], [message.parts])
  const [copied, setCopied] = useState(false)

  // Every document any tool returned in this turn, so citation chips can show a preview.
  const docs = useMemo(() => {
    const map = new Map<string, DocCard>()
    for (const p of parts) {
      if (p.kind !== 'tool' || !p.data) continue
      for (const d of [...(p.data.hits ?? []), ...(p.data.samples ?? []), ...(p.data.context ?? [])]) map.set(d.id, d)
      if (p.data.document) map.set(p.data.document.id, p.data.document)
    }
    return map
  }, [parts])

  const lastIndex = parts.length - 1
  const waiting = message.streaming && parts.length === 0

  return (
    <div className="group flex gap-3">
      <AgentIcon agent={agent} className="mt-0.5 size-7" />
      <div className="min-w-0 flex-1 space-y-3">
        {waiting && (
          <div className="flex items-center gap-2 pt-1 text-sm text-muted-foreground">
            <span className="flex gap-1">
              <span className="size-1.5 animate-bounce rounded-full bg-current [animation-delay:-0.3s]" />
              <span className="size-1.5 animate-bounce rounded-full bg-current [animation-delay:-0.15s]" />
              <span className="size-1.5 animate-bounce rounded-full bg-current" />
            </span>
          </div>
        )}
        {parts.map((part, i) => {
          switch (part.kind) {
            case 'reasoning':
              return <ReasoningBlock key={i} text={part.text} active={!!message.streaming && i === lastIndex} />
            case 'tool':
              return <ToolCallCard key={part.id + i} part={part} />
            case 'notice':
              return (
                <p key={i} className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <Info className="size-3.5" /> {part.text}
                </p>
              )
            case 'text':
              return (
                <AnswerMarkdown key={i} text={part.text} docs={docs} streaming={message.streaming && i === lastIndex} />
              )
          }
        })}
        {message.error && (
          <div className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
            <TriangleAlert className="mt-0.5 size-4 shrink-0" />
            <span className="break-words">{message.error}</span>
          </div>
        )}
        {!message.streaming && message.content && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100">
            <Button
              variant="ghost"
              size="icon"
              className="size-7"
              aria-label="Copy answer"
              onClick={() => {
                navigator.clipboard.writeText(message.content)
                setCopied(true)
                setTimeout(() => setCopied(false), 1200)
              }}
            >
              {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
            </Button>
            {message.elapsedMs !== undefined && <span>{(message.elapsedMs / 1000).toFixed(1)}s</span>}
          </div>
        )}
      </div>
    </div>
  )
}
