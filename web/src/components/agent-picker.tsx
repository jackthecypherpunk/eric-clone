import { Check, ChevronDown } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { AGENT_LIST, AGENTS, type AgentId } from '@/lib/agents'
import { cn } from '@/lib/utils'

export function AgentIcon({ agent, className }: { agent: AgentId; className?: string }) {
  const meta = AGENTS[agent]
  const Icon = meta.icon
  return (
    <span className={cn('flex shrink-0 items-center justify-center rounded-full', meta.tint, className)}>
      <Icon className="size-[60%]" />
    </span>
  )
}

/** Asked every time a new chat is started. */
export function NewChatDialog({
  open,
  onOpenChange,
  persona,
  onPick,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  persona: string
  onPick: (agent: AgentId) => void
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>New chat</DialogTitle>
          <DialogDescription>Who do you want to talk to? You can switch later inside the chat.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-3 sm:grid-cols-2">
          {AGENT_LIST.map((a) => (
            <button
              key={a.id}
              autoFocus={a.id === 'clone'}
              onClick={() => onPick(a.id)}
              className="flex flex-col gap-3 rounded-xl border p-4 text-start transition-colors hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
            >
              <AgentIcon agent={a.id} className="size-10" />
              <div>
                <p className="font-semibold">{a.label}</p>
                <p className="mt-1 text-sm leading-5 text-muted-foreground">{a.tagline(persona)}</p>
              </div>
            </button>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  )
}

/** Compact switcher shown in the chat header. */
export function AgentSwitcher({
  agent,
  persona,
  disabled,
  onChange,
}: {
  agent: AgentId
  persona: string
  disabled?: boolean
  onChange: (a: AgentId) => void
}) {
  const meta = AGENTS[agent]
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild disabled={disabled}>
        <Button variant="ghost" className="h-9 min-w-0 gap-2 px-2">
          <AgentIcon agent={agent} className="size-6" />
          <span className="truncate font-medium">{meta.label}</span>
          <ChevronDown className="size-3.5 text-muted-foreground" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-72">
        <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">Agent for this chat</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {AGENT_LIST.map((a) => (
          <DropdownMenuItem key={a.id} onSelect={() => onChange(a.id)} className="items-start gap-3 py-2">
            <AgentIcon agent={a.id} className="mt-0.5 size-7" />
            <div className="min-w-0 flex-1">
              <p className="font-medium">{a.label}</p>
              <p className="text-xs leading-4 text-muted-foreground">{a.tagline(persona)}</p>
            </div>
            {a.id === agent && <Check className="mt-1 size-4" />}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
