import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { CornerUpLeft, FileText, Send } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { api, type DocCard } from '@/lib/api'

const ViewerContext = createContext<(id: string) => void>(() => {})

export const useOpenSource = () => useContext(ViewerContext)

export function SourceIcon({ type, className }: { type: DocCard['source_type']; className?: string }) {
  return type === 'weblog' ? <FileText className={className} /> : <Send className={className} />
}

export function docLabel(doc: Pick<DocCard, 'source_type' | 'source' | 'message_id' | 'pages'>) {
  if (doc.source_type === 'weblog') return doc.pages ? `${doc.source} · p. ${doc.pages.split(',')[0]}` : doc.source
  return doc.message_id ? `${doc.source} #${doc.message_id}` : doc.source
}

export function SourceViewerProvider({ children }: { children: ReactNode }) {
  const [openId, setOpenId] = useState<string | null>(null)
  const [data, setData] = useState<{ document: DocCard; context: DocCard[] } | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!openId) return
    let cancelled = false
    setData(null)
    setError(null)
    api
      .document(openId)
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError(String(e.message ?? e)))
    return () => {
      cancelled = true
    }
  }, [openId])

  const doc = data?.document
  const before = data?.context.filter((c) => c.relation === 'before') ?? []
  const after = data?.context.filter((c) => c.relation === 'after') ?? []
  const parent = data?.context.find((c) => c.relation === 'replied to')
  const blogSiblings = doc?.source_type === 'weblog' ? (data?.context ?? []) : []

  return (
    <ViewerContext.Provider value={setOpenId}>
      {children}
      <Sheet open={!!openId} onOpenChange={(o) => !o && setOpenId(null)}>
        <SheetContent className="w-full gap-0 p-0 sm:max-w-xl">
          <SheetHeader className="border-b">
            <SheetTitle className="flex items-center gap-2">
              {doc && <SourceIcon type={doc.source_type} className="size-4 text-muted-foreground" />}
              {doc ? docLabel(doc) : 'Loading source…'}
            </SheetTitle>
            <SheetDescription className="flex flex-wrap items-center gap-2">
              {doc?.date && <span>{doc.date}</span>}
              {doc && <code className="rounded bg-muted px-1.5 py-0.5 text-xs">{doc.id}</code>}
            </SheetDescription>
          </SheetHeader>
          <ScrollArea className="min-h-0 flex-1">
            <div className="space-y-5 p-4">
              {error && <p className="text-sm text-destructive">{error}</p>}
              {!data && !error && (
                <div className="space-y-2">
                  <Skeleton className="h-4 w-full" />
                  <Skeleton className="h-4 w-11/12" />
                  <Skeleton className="h-4 w-4/5" />
                </div>
              )}
              {parent && (
                <ContextCard doc={parent} label={<><CornerUpLeft className="size-3" /> In reply to</>} onOpen={setOpenId} />
              )}
              {before.map((d) => (
                <ContextCard key={d.id} doc={d} label="Earlier post" onOpen={setOpenId} />
              ))}
              {doc && (
                <article className="rounded-lg border bg-card p-4 shadow-xs">
                  {doc.title && (
                    <h3 dir="auto" className="mb-3 text-lg font-semibold">
                      {doc.title}
                    </h3>
                  )}
                  <p dir="auto" className="whitespace-pre-wrap text-[15px] leading-8">
                    {doc.text}
                  </p>
                </article>
              )}
              {after.map((d) => (
                <ContextCard key={d.id} doc={d} label="Later post" onOpen={setOpenId} />
              ))}
              {blogSiblings.length > 0 && (
                <div className="space-y-2">
                  <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
                    Other parts of this blog post
                  </p>
                  {blogSiblings.map((d) => (
                    <ContextCard key={d.id} doc={d} label={d.id} onOpen={setOpenId} />
                  ))}
                </div>
              )}
            </div>
          </ScrollArea>
        </SheetContent>
      </Sheet>
    </ViewerContext.Provider>
  )
}

function ContextCard({ doc, label, onOpen }: { doc: DocCard; label: ReactNode; onOpen: (id: string) => void }) {
  return (
    <button
      onClick={() => onOpen(doc.id)}
      className="block w-full rounded-lg border border-dashed p-3 text-start transition-colors hover:bg-muted/60"
    >
      <div className="mb-1 flex items-center gap-2 text-xs text-muted-foreground">
        <Badge variant="outline" className="gap-1 font-normal">
          {label}
        </Badge>
        {doc.date}
      </div>
      <p dir="auto" className="line-clamp-3 text-sm leading-7 text-muted-foreground">
        {doc.text}
      </p>
    </button>
  )
}
