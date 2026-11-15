import { useEffect, useMemo, useRef, useState, type ClipboardEvent, type DragEvent, type KeyboardEvent } from 'react'
import { ArrowDown, ArrowUp, FileText, Globe, LoaderCircle, Menu, Paperclip, Square, TriangleAlert, X } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { AGENTS, type AgentId } from '@/lib/agents'
import { api, type Attachment, type Status } from '@/lib/api'
import type { Conversation, DraftOptions } from '@/lib/conversations'
import { cn } from '@/lib/utils'
import { AgentIcon, AgentSwitcher } from './agent-picker'
import { AssistantMessage, UserMessage } from './message'

const ACCEPT = 'image/*,.pdf,.docx,.txt,.md,.csv,.tsv,.json,.html,.htm,.xml,.srt,.vtt'
const MAX_FILES = 10

interface PendingFile {
  key: string
  name: string
  previewUrl?: string
  status: 'uploading' | 'ready' | 'error'
  meta?: Attachment
}

export function ChatView({
  conversation,
  options,
  onOptionsChange,
  status,
  busy,
  onSend,
  onStop,
  onOpenMenu,
}: {
  conversation: Conversation | null
  options: DraftOptions
  onOptionsChange: (patch: Partial<DraftOptions>) => void
  status: Status | null
  busy: boolean
  onSend: (text: string, attachments: Attachment[]) => void
  onStop: () => void
  onOpenMenu: () => void
}) {
  const [draft, setDraft] = useState('')
  const [files, setFiles] = useState<PendingFile[]>([])
  const [dragging, setDragging] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const stickToBottom = useRef(true)
  const [showJump, setShowJump] = useState(false)
  const persona = status?.persona ?? 'Eric'
  const messages = useMemo(() => conversation?.messages ?? [], [conversation?.messages])
  const agent = AGENTS[options.agent]
  const uploading = files.some((f) => f.status === 'uploading')
  const ready = files.filter((f) => f.status === 'ready' && f.meta).map((f) => f.meta!)

  // Follow the stream only while the reader is already at the bottom.
  useEffect(() => {
    const el = scrollRef.current
    if (el && stickToBottom.current) el.scrollTop = el.scrollHeight
  }, [messages])

  const onScroll = () => {
    const el = scrollRef.current
    if (!el) return
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80
    stickToBottom.current = atBottom
    setShowJump(!atBottom)
  }

  const addFiles = (list: FileList | File[]) => {
    const incoming = Array.from(list).slice(0, MAX_FILES - files.length)
    if (list.length > incoming.length) toast.message(`Up to ${MAX_FILES} files per message.`)
    for (const file of incoming) {
      const key = crypto.randomUUID()
      const previewUrl = file.type.startsWith('image/') ? URL.createObjectURL(file) : undefined
      setFiles((fs) => [...fs, { key, name: file.name, previewUrl, status: 'uploading' }])
      api
        .upload(file)
        .then((meta) => {
          setFiles((fs) => fs.map((f) => (f.key === key ? { ...f, status: 'ready', meta } : f)))
          if (meta.warning) toast.warning(`${meta.name}: ${meta.warning}`)
          else if (meta.truncated) toast.message(`${meta.name} is long; only the first part will be read.`)
        })
        .catch((e) => {
          setFiles((fs) => fs.map((f) => (f.key === key ? { ...f, status: 'error' } : f)))
          toast.error(`${file.name}: ${(e as Error).message}`)
        })
    }
  }

  const removeFile = (key: string) =>
    setFiles((fs) => {
      const f = fs.find((x) => x.key === key)
      if (f?.previewUrl) URL.revokeObjectURL(f.previewUrl)
      return fs.filter((x) => x.key !== key)
    })

  const submit = (text = draft) => {
    if ((!text.trim() && !ready.length) || busy || uploading) return
    onSend(text, ready)
    setDraft('')
    files.forEach((f) => f.previewUrl && URL.revokeObjectURL(f.previewUrl))
    setFiles([])
    stickToBottom.current = true
  }

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      submit()
    }
  }

  const onPaste = (e: ClipboardEvent) => {
    const pasted = Array.from(e.clipboardData.files)
    if (pasted.length) {
      e.preventDefault()
      addFiles(pasted)
    }
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragging(false)
    if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files)
  }

  const canSend = (draft.trim() || ready.length) && !uploading && status?.ready

  return (
    <div
      className="relative flex h-full min-h-0 flex-col"
      onDragOver={(e) => {
        if (e.dataTransfer.types.includes('Files')) {
          e.preventDefault()
          setDragging(true)
        }
      }}
      onDragLeave={(e) => e.currentTarget === e.target && setDragging(false)}
      onDrop={onDrop}
    >
      <header className="flex h-12 shrink-0 items-center gap-1 border-b px-2 md:px-4">
        <Button variant="ghost" size="icon" className="md:hidden" onClick={onOpenMenu} aria-label="Open menu">
          <Menu />
        </Button>
        <AgentSwitcher
          agent={options.agent}
          persona={persona}
          disabled={busy}
          onChange={(a: AgentId) => {
            if (a === options.agent) return
            onOptionsChange({ agent: a })
            if (messages.length) toast.message(`Switched to ${AGENTS[a].label}. Earlier answers stay as they were.`)
          }}
        />
        {conversation && (
          <span dir="auto" className="min-w-0 truncate text-sm text-muted-foreground">
            {conversation.title}
          </span>
        )}
      </header>

      <div ref={scrollRef} onScroll={onScroll} className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto">
        {messages.length === 0 ? (
          <div className="mx-auto flex min-h-full max-w-2xl flex-col justify-center px-4 py-10">
            <div className="mb-8 space-y-3">
              <AgentIcon agent={options.agent} className="size-11" />
              <h1 className="text-2xl font-semibold tracking-tight">
                {options.agent === 'clone' ? `Talk to ${persona}` : `Study ${persona}`}
              </h1>
              <p className="text-sm leading-6 text-muted-foreground">
                {agent.tagline(persona)} It searches the writing itself and footnotes its claims. Click a footnote to read
                the original post.
              </p>
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              {agent.suggestions.map((s) => (
                <button
                  key={s}
                  dir="auto"
                  disabled={!status?.ready}
                  onClick={() => submit(s)}
                  className="rounded-xl border p-3 text-start text-sm leading-6 transition-colors hover:bg-muted disabled:opacity-50"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="mx-auto max-w-3xl space-y-8 px-4 py-8">
            {messages.map((m) =>
              m.role === 'user' ? (
                <UserMessage key={m.id} message={m} />
              ) : (
                <AssistantMessage key={m.id} message={m} agent={m.agent ?? conversation?.agent ?? 'clone'} />
              ),
            )}
          </div>
        )}
      </div>

      {showJump && (
        <Button
          variant="outline"
          size="icon"
          className="absolute bottom-32 left-1/2 size-8 -translate-x-1/2 rounded-full shadow-sm"
          onClick={() => {
            stickToBottom.current = true
            scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
          }}
          aria-label="Jump to latest"
        >
          <ArrowDown />
        </Button>
      )}

      {dragging && (
        <div className="pointer-events-none absolute inset-2 z-10 flex items-center justify-center rounded-2xl border-2 border-dashed border-primary/50 bg-background/80 text-sm font-medium">
          Drop images, PDFs or text files
        </div>
      )}

      <div className="mx-auto w-full max-w-3xl px-4 pb-4">
        <div className="rounded-2xl border bg-background p-2 shadow-sm focus-within:ring-2 focus-within:ring-ring/30">
          {files.length > 0 && (
            <div className="flex flex-wrap gap-2 px-1 pt-1 pb-2">
              {files.map((f) => (
                <FileChip key={f.key} file={f} onRemove={() => removeFile(f.key)} />
              ))}
            </div>
          )}
          <Textarea
            dir="auto"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
            onPaste={onPaste}
            placeholder={
              status?.ready
                ? options.agent === 'clone'
                  ? `Ask ${persona} anything… (Persian or English)`
                  : `Ask about ${persona}'s writing…`
                : 'The archive is still being indexed…'
            }
            className="max-h-48 min-h-12 resize-none border-0 bg-transparent shadow-none focus-visible:ring-0 dark:bg-transparent"
            rows={1}
          />
          <div className="flex items-center gap-1 pt-1">
            <input
              ref={fileInput}
              type="file"
              multiple
              accept={ACCEPT}
              className="hidden"
              onChange={(e) => {
                if (e.target.files) addFiles(e.target.files)
                e.target.value = ''
              }}
            />
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="ghost" size="icon" className="size-8 rounded-full" onClick={() => fileInput.current?.click()} aria-label="Attach files">
                  <Paperclip />
                </Button>
              </TooltipTrigger>
              <TooltipContent>Attach images, PDF, DOCX or text (or drop / paste)</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="sm"
                  aria-pressed={options.webSearch}
                  onClick={() => onOptionsChange({ webSearch: !options.webSearch })}
                  className={cn(
                    'h-8 gap-1.5 rounded-full px-2.5',
                    options.webSearch && 'bg-sky-500/15 text-sky-700 hover:bg-sky-500/25 dark:text-sky-300',
                  )}
                >
                  <Globe /> Web
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                {options.webSearch ? 'Web search on: the agent can look up recent news' : 'Let the agent search the live web'}
              </TooltipContent>
            </Tooltip>
            <span className="ms-auto min-w-0 truncate px-1 text-xs text-muted-foreground">{status?.llm.model}</span>
            {busy ? (
              <Button size="icon" variant="secondary" className="size-8 shrink-0 rounded-full" onClick={onStop} aria-label="Stop">
                <Square className="size-3.5 fill-current" />
              </Button>
            ) : (
              <Button size="icon" className="size-8 shrink-0 rounded-full" onClick={() => submit()} disabled={!canSend} aria-label="Send">
                {uploading ? <LoaderCircle className="animate-spin" /> : <ArrowUp />}
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function FileChip({ file, onRemove }: { file: PendingFile; onRemove: () => void }) {
  return (
    <div
      className={cn(
        'group relative flex h-12 max-w-52 items-center gap-2 rounded-lg border bg-muted/40 pe-7 text-xs',
        file.previewUrl ? 'ps-1' : 'ps-2.5',
        file.status === 'error' && 'border-destructive/50 text-destructive',
      )}
    >
      {file.previewUrl ? (
        <img src={file.previewUrl} alt="" className="size-10 shrink-0 rounded-md object-cover" />
      ) : file.status === 'error' ? (
        <TriangleAlert className="size-4 shrink-0" />
      ) : (
        <FileText className="size-4 shrink-0 text-muted-foreground" />
      )}
      <div className="min-w-0">
        <p className="truncate font-medium">{file.name}</p>
        <p className="text-muted-foreground">
          {file.status === 'uploading'
            ? 'Uploading…'
            : file.status === 'error'
              ? 'Failed'
              : file.meta?.pages
                ? `${file.meta.pages} pages`
                : file.meta?.kind}
        </p>
      </div>
      {file.status === 'uploading' && <LoaderCircle className="absolute end-2 size-3.5 animate-spin text-muted-foreground" />}
      {file.status !== 'uploading' && (
        <button onClick={onRemove} className="absolute end-1.5 rounded-full p-0.5 hover:bg-muted" aria-label={`Remove ${file.name}`}>
          <X className="size-3.5" />
        </button>
      )}
    </div>
  )
}
