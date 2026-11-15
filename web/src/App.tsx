import { useCallback, useEffect, useState } from 'react'
import { Database, Menu, Moon, Plus, Search, Settings2, Sun, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet'
import { Toaster } from '@/components/ui/sonner'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { AgentIcon, NewChatDialog } from '@/components/agent-picker'
import { ChatView } from '@/components/chat-view'
import { ResearchView } from '@/components/research-view'
import { SettingsDialog } from '@/components/settings-dialog'
import { SourceViewerProvider } from '@/components/source-viewer'
import { AGENTS } from '@/lib/agents'
import { api, type Status } from '@/lib/api'
import { useConversations, type Conversation } from '@/lib/conversations'
import { cn } from '@/lib/utils'

type View = 'chat' | 'research'

function useTheme() {
  const [dark, setDark] = useState(() => {
    try {
      const saved = localStorage.getItem('eric.theme')
      if (saved) return saved === 'dark'
    } catch {
      /* ignore */
    }
    return window.matchMedia('(prefers-color-scheme: dark)').matches
  })
  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark)
    try {
      localStorage.setItem('eric.theme', dark ? 'dark' : 'light')
    } catch {
      /* ignore */
    }
  }, [dark])
  return [dark, setDark] as const
}

export default function App() {
  const chat = useConversations()
  const [status, setStatus] = useState<Status | null>(null)
  const [statusError, setStatusError] = useState(false)
  const [view, setView] = useState<View>('chat')
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [newChatOpen, setNewChatOpen] = useState(false)
  const [mobileNav, setMobileNav] = useState(false)
  const [dark, setDark] = useTheme()
  const persona = status?.persona ?? 'Eric'

  const refreshStatus = useCallback(() => {
    api
      .status()
      .then((s) => {
        setStatus(s)
        setStatusError(false)
      })
      .catch(() => setStatusError(true))
  }, [])

  useEffect(() => {
    refreshStatus()
    // Poll while the backend is down or still indexing.
    const t = setInterval(() => (!status?.ready || statusError) && refreshStatus(), 5000)
    return () => clearInterval(t)
  }, [refreshStatus, status?.ready, statusError])

  const deleteConversation = (c: Conversation) => {
    const undo = chat.deleteConversation(c.id)
    toast(`Deleted “${c.title.slice(0, 40)}”`, { action: { label: 'Undo', onClick: undo } })
  }

  const sidebar = (
    <Sidebar
      conversations={chat.conversations}
      activeId={view === 'chat' ? chat.activeId : null}
      view={view}
      persona={persona}
      onNew={() => {
        setMobileNav(false)
        setNewChatOpen(true)
      }}
      onSelect={(id) => {
        chat.setActiveId(id)
        setView('chat')
        setMobileNav(false)
      }}
      onDelete={deleteConversation}
      onResearch={() => {
        setView('research')
        setMobileNav(false)
      }}
      status={status}
      statusError={statusError}
      onSettings={() => setSettingsOpen(true)}
      dark={dark}
      onToggleTheme={() => setDark(!dark)}
    />
  )

  return (
    <TooltipProvider delayDuration={200}>
      <SourceViewerProvider>
        <div className="flex h-dvh overflow-hidden bg-background">
          <aside className="hidden w-64 shrink-0 border-e bg-sidebar md:flex">{sidebar}</aside>
          <Sheet open={mobileNav} onOpenChange={setMobileNav}>
            <SheetContent side="left" className="w-72 max-w-[85vw] bg-sidebar p-0">
              <SheetTitle className="sr-only">Navigation</SheetTitle>
              {sidebar}
            </SheetContent>
          </Sheet>
          <main className="flex min-w-0 flex-1 flex-col">
            {view === 'chat' ? (
              <ChatView
                key={chat.activeId ?? 'new'}
                conversation={chat.active}
                options={chat.options}
                onOptionsChange={chat.setOptions}
                status={status}
                busy={chat.busy}
                onSend={chat.send}
                onStop={chat.stop}
                onOpenMenu={() => setMobileNav(true)}
              />
            ) : (
              <>
                <header className="flex h-12 shrink-0 items-center gap-2 border-b px-2 md:hidden">
                  <Button variant="ghost" size="icon" onClick={() => setMobileNav(true)} aria-label="Open menu">
                    <Menu />
                  </Button>
                  <span className="text-sm font-medium">Research</span>
                </header>
                <div className="min-h-0 flex-1">
                  <ResearchView />
                </div>
              </>
            )}
          </main>
        </div>
        <NewChatDialog
          open={newChatOpen}
          onOpenChange={setNewChatOpen}
          persona={persona}
          onPick={(agent) => {
            chat.newConversation(agent)
            setView('chat')
            setNewChatOpen(false)
          }}
        />
        <SettingsDialog
          open={settingsOpen}
          onOpenChange={setSettingsOpen}
          current={status?.llm}
          onSaved={(llm) => setStatus((s) => (s ? { ...s, llm } : s))}
        />
        <Toaster position="top-center" />
      </SourceViewerProvider>
    </TooltipProvider>
  )
}

function Sidebar(props: {
  conversations: Conversation[]
  activeId: string | null
  view: View
  persona: string
  onNew: () => void
  onSelect: (id: string) => void
  onDelete: (c: Conversation) => void
  onResearch: () => void
  status: Status | null
  statusError: boolean
  onSettings: () => void
  dark: boolean
  onToggleTheme: () => void
}) {
  const { status } = props
  return (
    <div className="flex h-full w-full min-w-0 flex-col">
      <div className="space-y-1 p-3">
        <div className="flex min-w-0 items-center gap-2 px-2 pt-1 pb-3">
          <div className="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary text-sm font-semibold text-primary-foreground">
            {props.persona.slice(0, 1)}
          </div>
          <span className="truncate font-semibold">{props.persona}</span>
          <span className="truncate text-xs text-muted-foreground">archive</span>
        </div>
        <Button variant="outline" className="w-full justify-start" onClick={props.onNew}>
          <Plus /> New chat
        </Button>
        <Button
          variant="ghost"
          className={cn('w-full justify-start', props.view === 'research' && 'bg-sidebar-accent')}
          onClick={props.onResearch}
        >
          <Search /> Research the archive
        </Button>
      </div>

      {/* Plain overflow container: Radix ScrollArea's table layout breaks text truncation. */}
      <nav className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto px-3 pb-3" aria-label="Conversations">
        {props.conversations.length > 0 && <p className="px-2 pt-2 pb-1 text-xs font-medium text-muted-foreground">History</p>}
        <ul className="space-y-0.5">
          {props.conversations.map((c) => {
            const meta = AGENTS[c.agent]
            const active = c.id === props.activeId
            return (
              <li
                key={c.id}
                className={cn(
                  'group grid grid-cols-[minmax(0,1fr)_auto] items-center rounded-md text-sm hover:bg-sidebar-accent',
                  active && 'bg-sidebar-accent',
                )}
              >
                <button
                  onClick={() => props.onSelect(c.id)}
                  className="flex min-w-0 items-center gap-2 rounded-md px-2 py-1.5 text-start focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                  title={`${meta.label} · ${c.title}`}
                >
                  <AgentIcon agent={c.agent} className="size-5" />
                  <span dir="auto" className="min-w-0 flex-1 truncate">
                    {c.title}
                  </span>
                </button>
                <Button
                  variant="ghost"
                  size="icon"
                  className={cn(
                    'me-1 size-7 text-muted-foreground hover:text-destructive',
                    // Visible on hover/focus with a mouse, always visible on touch screens.
                    'opacity-0 group-hover:opacity-100 focus-visible:opacity-100 [@media(hover:none)]:opacity-100',
                    active && 'opacity-100',
                  )}
                  onClick={() => props.onDelete(c)}
                  aria-label={`Delete conversation ${c.title}`}
                >
                  <Trash2 className="size-3.5" />
                </Button>
              </li>
            )
          })}
        </ul>
      </nav>

      <div className="space-y-2 border-t p-3">
        <Tooltip>
          <TooltipTrigger asChild>
            <div className="flex min-w-0 items-center gap-2 rounded-md px-2 py-1 text-xs text-muted-foreground">
              <span
                className={cn(
                  'size-2 shrink-0 rounded-full',
                  props.statusError ? 'bg-destructive' : status?.ready ? 'bg-emerald-500' : 'animate-pulse bg-amber-500',
                )}
              />
              <Database className="size-3.5 shrink-0" />
              <span className="truncate">
                {props.statusError
                  ? 'Backend offline'
                  : status
                    ? status.ready
                      ? `${status.corpus.documents.toLocaleString()} documents indexed`
                      : 'Index not built yet'
                    : 'Connecting…'}
              </span>
            </div>
          </TooltipTrigger>
          {status && (
            <TooltipContent side="top" className="max-w-xs">
              <div className="space-y-1">
                {Object.entries(status.corpus.by_source).map(([k, v]) => (
                  <p key={k}>
                    {k}: {v.toLocaleString()}
                  </p>
                ))}
                <p>
                  {status.vectors.toLocaleString()} vectors · {status.embed_model}
                </p>
                {status.corpus.date_range && <p>{status.corpus.date_range.join(' → ')}</p>}
              </div>
            </TooltipContent>
          )}
        </Tooltip>
        <div className="flex min-w-0 items-center gap-1">
          <Button
            variant="ghost"
            className="min-w-0 flex-1 shrink justify-start"
            onClick={props.onSettings}
            title={status?.llm.model ? `Model: ${status.llm.model}` : 'Model settings'}
          >
            <Settings2 />
            <span className="min-w-0 truncate">{status?.llm.model ?? 'Model settings'}</span>
          </Button>
          <Button variant="ghost" size="icon" onClick={props.onToggleTheme} aria-label="Toggle theme">
            {props.dark ? <Sun /> : <Moon />}
          </Button>
        </div>
      </div>
    </div>
  )
}
