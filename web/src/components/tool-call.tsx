import { useState } from 'react'
import { BarChart3, Brain, Check, ChevronRight, ExternalLink, FileSearch, Globe, LoaderCircle, Newspaper, Search, TriangleAlert } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import type { DocCard, WebResult } from '@/lib/api'
import type { Part } from '@/lib/conversations'
import { cn } from '@/lib/utils'
import { SourceIcon, docLabel, useOpenSource } from './source-viewer'

type ToolPart = Extract<Part, { kind: 'tool' }>

const TOOL_META: Record<string, { icon: typeof Search; running: string; done: string }> = {
  search_archive: { icon: Search, running: 'Searching the archive', done: 'Searched the archive' },
  read_document: { icon: FileSearch, running: 'Reading a document', done: 'Read a document' },
  find_mentions: { icon: BarChart3, running: 'Counting mentions', done: 'Counted mentions' },
  web_search: { icon: Globe, running: 'Searching the web', done: 'Searched the web' },
  fetch_page: { icon: Newspaper, running: 'Reading a web page', done: 'Read a web page' },
}

function argChips(args: ToolPart['args']): string[] {
  if (typeof args === 'string') return [args]
  const chips: string[] = []
  for (const key of ['query', 'phrase', 'doc_id'] as const) if (args[key]) chips.push(String(args[key]))
  if (args.url) chips.push(String(args.url).replace(/^https?:\/\/(www\.)?/, ''))
  if (args.recency) chips.push(`past ${args.recency}`)
  if (args.news) chips.push('news')
  if (args.source && args.source !== 'all') chips.push(String(args.source))
  if (args.date_from || args.date_to) chips.push(`${args.date_from ?? '…'} → ${args.date_to ?? '…'}`)
  return chips
}

export function ToolCallCard({ part }: { part: ToolPart }) {
  const [open, setOpen] = useState(false)
  const meta = TOOL_META[part.name] ?? { icon: Search, running: part.name, done: part.name }
  const Icon = meta.icon
  const chips = argChips(part.args)

  return (
    <Collapsible open={open} onOpenChange={setOpen} className="rounded-lg border bg-muted/30 text-sm">
      <CollapsibleTrigger className="flex w-full items-center gap-2 px-3 py-2 text-start">
        <span
          className={cn(
            'flex size-6 shrink-0 items-center justify-center rounded-md border bg-background',
            part.status === 'error' && 'border-destructive/40 text-destructive',
          )}
        >
          {part.status === 'running' ? (
            <LoaderCircle className="size-3.5 animate-spin" />
          ) : part.status === 'error' ? (
            <TriangleAlert className="size-3.5" />
          ) : (
            <Icon className="size-3.5" />
          )}
        </span>
        <span className="shrink-0 font-medium">{part.status === 'running' ? meta.running : meta.done}</span>
        <span className="flex min-w-0 flex-1 items-center gap-1 overflow-hidden">
          {chips.map((c) => (
            <Badge key={c} variant="secondary" dir="auto" className="max-w-56 truncate font-normal">
              {c}
            </Badge>
          ))}
        </span>
        {part.summary && (
          <span className="hidden shrink-0 items-center gap-1 text-xs text-muted-foreground sm:flex">
            {part.status === 'done' && <Check className="size-3" />}
            {part.summary}
            {part.elapsedMs !== undefined && ` · ${(part.elapsedMs / 1000).toFixed(1)}s`}
          </span>
        )}
        <ChevronRight className={cn('size-4 shrink-0 text-muted-foreground transition-transform', open && 'rotate-90')} />
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="space-y-2 border-t px-3 py-3">
          <ToolBody part={part} />
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}

function ToolBody({ part }: { part: ToolPart }) {
  const data = part.data
  if (!data) return <p className="text-muted-foreground">Waiting for results…</p>
  if (data.error) return <p className="text-destructive">{data.error}</p>
  if (data.hits) {
    return data.hits.length ? (
      <div className="grid gap-2">
        {data.hits.map((d) => (
          <HitRow key={d.id} doc={d} />
        ))}
      </div>
    ) : (
      <p className="text-muted-foreground">Nothing matched.</p>
    )
  }
  if (data.document) return <HitRow doc={data.document} />
  if (data.results) return data.results.length ? <div className="grid gap-2">{data.results.map((r) => <WebRow key={r.url} result={r} />)}</div> : <p className="text-muted-foreground">No web results.</p>
  if (data.page) return <WebRow result={{ title: data.page.title, url: data.page.url, snippet: data.page.excerpt, date: '' }} />
  if (data.by_year) return <MentionsChart total={data.total ?? 0} byYear={data.by_year} samples={data.samples ?? []} />
  return null
}

export function HitRow({ doc, lines = 2 }: { doc: DocCard; lines?: number }) {
  const open = useOpenSource()
  return (
    <button
      onClick={() => open(doc.id)}
      className="group block w-full rounded-md border bg-background p-2.5 text-start transition-colors hover:border-foreground/20"
    >
      <div className="mb-1 flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
        <SourceIcon type={doc.source_type} className="size-3" />
        <span className="truncate">{docLabel(doc)}</span>
        <span>·</span>
        <span className="shrink-0">{doc.date || 'undated'}</span>
        {doc.title && (
          <span dir="auto" className="truncate font-medium text-foreground/80">
            · {doc.title}
          </span>
        )}
      </div>
      <p dir="auto" className={cn('text-[13px] leading-6 text-foreground/80', lines === 2 ? 'line-clamp-2' : 'line-clamp-4')}>
        {doc.text}
      </p>
    </button>
  )
}

function WebRow({ result }: { result: WebResult }) {
  let host = result.url
  try {
    host = new URL(result.url).hostname.replace(/^www\./, '')
  } catch {
    /* keep raw */
  }
  return (
    <a
      href={result.url}
      target="_blank"
      rel="noreferrer"
      className="block rounded-md border bg-background p-2.5 transition-colors hover:border-foreground/20"
    >
      <div className="mb-1 flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
        <ExternalLink className="size-3 shrink-0" />
        <span className="truncate">{host}</span>
        {result.date && <span className="shrink-0">· {result.date.slice(0, 10)}</span>}
      </div>
      <p dir="auto" className="truncate text-[13px] font-medium">{result.title}</p>
      <p dir="auto" className="line-clamp-2 text-[13px] leading-6 text-foreground/70">{result.snippet}</p>
    </a>
  )
}

export function MentionsChart({ total, byYear, samples }: { total: number; byYear: Record<string, number>; samples: DocCard[] }) {
  const entries = Object.entries(byYear)
  const max = Math.max(1, ...entries.map(([, n]) => n))
  return (
    <div className="space-y-3">
      <p>
        <span className="font-semibold tabular-nums">{total.toLocaleString()}</span>{' '}
        <span className="text-muted-foreground">documents contain this phrase</span>
      </p>
      <div className="flex h-28 items-end gap-1">
        {entries.map(([year, n]) => (
          <div key={year} className="flex h-full flex-1 flex-col items-center justify-end gap-1" title={`${year}: ${n}`}>
            <span className="text-[10px] text-muted-foreground tabular-nums">{n}</span>
            <div className="w-full max-w-8 rounded-t-sm bg-primary/80" style={{ height: `${(n / max) * 100}%` }} />
            <span className="text-[10px] text-muted-foreground tabular-nums">{year.slice(2)}</span>
          </div>
        ))}
      </div>
      {samples.length > 0 && (
        <div className="grid gap-2">
          {samples.map((d) => (
            <HitRow key={d.id} doc={d} />
          ))}
        </div>
      )}
    </div>
  )
}

export function ReasoningBlock({ text, active }: { text: string; active: boolean }) {
  const [open, setOpen] = useState(false)
  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground">
        <Brain className={cn('size-3.5', active && 'animate-pulse')} />
        {active ? 'Thinking…' : 'Thought process'}
        <ChevronRight className={cn('size-3 transition-transform', open && 'rotate-90')} />
      </CollapsibleTrigger>
      <CollapsibleContent>
        <p dir="auto" className="mt-2 border-s-2 ps-3 text-xs leading-6 whitespace-pre-wrap text-muted-foreground">
          {text}
        </p>
      </CollapsibleContent>
    </Collapsible>
  )
}
