import { useCallback, useEffect, useRef, useState } from 'react'
import type { AgentId } from './agents'
import { type AgentEvent, type Attachment, type ToolData, streamChat } from './api'

export type Part =
  | { kind: 'text'; text: string }
  | { kind: 'reasoning'; text: string }
  | { kind: 'notice'; text: string }
  | {
      kind: 'tool'
      id: string
      name: string
      args: Record<string, unknown> | string
      status: 'running' | 'done' | 'error'
      summary?: string
      data?: ToolData
      elapsedMs?: number
    }

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string // user text, or the assistant's final answer text
  attachments?: Attachment[] // user messages only
  agent?: AgentId // which agent wrote an assistant message
  parts?: Part[]
  error?: string
  elapsedMs?: number
  streaming?: boolean
}

export interface Conversation {
  id: string
  title: string
  createdAt: number
  agent: AgentId
  webSearch: boolean
  messages: Message[]
}

/** Options for the chat that hasn't been created yet (before its first message). */
export interface DraftOptions {
  agent: AgentId
  webSearch: boolean
}

const STORAGE_KEY = 'eric.conversations.v1'
const uid = () => crypto.randomUUID()

function load(): Conversation[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    const list = raw ? (JSON.parse(raw) as Conversation[]) : []
    // A reload mid-answer leaves a message flagged as streaming forever.
    return list.map((c) => ({
      ...c,
      agent: c.agent ?? 'clone', // conversations saved before agents existed
      webSearch: c.webSearch ?? false,
      messages: c.messages.map((m) => ({ ...m, streaming: false })),
    }))
  } catch {
    return []
  }
}

function save(list: Conversation[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(list))
  } catch {
    /* storage full or blocked: conversations just won't survive a reload */
  }
}

export function applyEvent(msg: Message, ev: AgentEvent): Message {
  const parts = [...(msg.parts ?? [])]
  const last = parts[parts.length - 1]
  switch (ev.type) {
    case 'token':
      if (last?.kind === 'text') parts[parts.length - 1] = { ...last, text: last.text + ev.text }
      else parts.push({ kind: 'text', text: ev.text })
      return { ...msg, parts, content: msg.content + ev.text }
    case 'reasoning':
      if (last?.kind === 'reasoning') parts[parts.length - 1] = { ...last, text: last.text + ev.text }
      else parts.push({ kind: 'reasoning', text: ev.text })
      return { ...msg, parts }
    case 'notice':
      parts.push({ kind: 'notice', text: ev.message })
      return { ...msg, parts }
    case 'tool_call':
      parts.push({ kind: 'tool', id: ev.id, name: ev.name, args: ev.arguments, status: 'running' })
      return { ...msg, parts }
    case 'tool_result':
      return {
        ...msg,
        parts: parts.map((p) =>
          p.kind === 'tool' && p.id === ev.id
            ? { ...p, status: ev.data?.error ? 'error' : 'done', summary: ev.summary, data: ev.data, elapsedMs: ev.elapsed_ms }
            : p,
        ),
      }
    case 'done':
      return { ...msg, streaming: false, elapsedMs: ev.elapsed_ms }
    case 'error':
      return { ...msg, streaming: false, error: ev.message }
  }
}

export function useConversations() {
  const [conversations, setConversations] = useState<Conversation[]>(load)
  const [activeId, setActiveId] = useState<string | null>(() => conversations[0]?.id ?? null)
  const [draft, setDraft] = useState<DraftOptions>({ agent: 'clone', webSearch: false })
  const [busy, setBusy] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    // Persist at most a couple of times per second while tokens stream in.
    const t = setTimeout(() => save(conversations), 400)
    return () => clearTimeout(t)
  }, [conversations])

  const active = conversations.find((c) => c.id === activeId) ?? null

  const updateMessage = useCallback((convId: string, msgId: string, fn: (m: Message) => Message) => {
    setConversations((list) =>
      list.map((c) => (c.id === convId ? { ...c, messages: c.messages.map((m) => (m.id === msgId ? fn(m) : m)) } : c)),
    )
  }, [])

  const newConversation = useCallback((agent: AgentId) => {
    abortRef.current?.abort()
    setActiveId(null)
    setDraft((d) => ({ ...d, agent }))
  }, [])

  /** Agent / web-search options of the active chat, or of the draft when no chat is open yet. */
  const options: DraftOptions = active ? { agent: active.agent, webSearch: active.webSearch } : draft
  const setOptions = useCallback(
    (patch: Partial<DraftOptions>) => {
      if (!activeId) return setDraft((d) => ({ ...d, ...patch }))
      setConversations((list) => list.map((c) => (c.id === activeId ? { ...c, ...patch } : c)))
    },
    [activeId],
  )

  /** Removes a conversation and returns a function that puts it back (for "Undo"). */
  const deleteConversation = useCallback(
    (id: string) => {
      if (id === activeId) abortRef.current?.abort()
      let removed: { conv: Conversation; index: number } | null = null
      setConversations((list) => {
        const index = list.findIndex((c) => c.id === id)
        if (index !== -1) removed = { conv: list[index], index }
        return list.filter((c) => c.id !== id)
      })
      setActiveId((cur) => (cur === id ? null : cur))
      return () => {
        const r = removed as { conv: Conversation; index: number } | null
        if (!r) return
        setConversations((list) => (list.some((c) => c.id === r.conv.id) ? list : [...list.slice(0, r.index), r.conv, ...list.slice(r.index)]))
      }
    },
    [activeId],
  )

  const stop = useCallback(() => abortRef.current?.abort(), [])

  const send = useCallback(
    async (text: string, attachments: Attachment[] = []) => {
      const content = text.trim()
      if ((!content && !attachments.length) || busy) return
      let conv = active
      if (!conv) {
        const title = content.slice(0, 60) || attachments.map((a) => a.name).join(', ').slice(0, 60)
        conv = { id: uid(), title, createdAt: Date.now(), ...draft, messages: [] }
        setConversations((list) => [conv!, ...list])
        setActiveId(conv.id)
      }
      const convId = conv.id
      const user: Message = { id: uid(), role: 'user', content, attachments }
      const assistant: Message = { id: uid(), role: 'assistant', content: '', parts: [], streaming: true, agent: conv.agent }
      const history = [...conv.messages, user]
        .filter((m) => (m.content || m.attachments?.length) && !m.error)
        .map((m) => ({ role: m.role, content: m.content, attachments: m.attachments?.map((a) => a.id) }))
      const chatOptions = { agent: conv.agent, web_search: conv.webSearch }

      setConversations((list) =>
        list.map((c) => (c.id === convId ? { ...c, messages: [...c.messages, user, assistant] } : c)),
      )
      const controller = new AbortController()
      abortRef.current = controller
      setBusy(true)
      try {
        for await (const ev of streamChat(history, chatOptions, controller.signal)) {
          updateMessage(convId, assistant.id, (m) => applyEvent(m, ev))
        }
        updateMessage(convId, assistant.id, (m) => ({ ...m, streaming: false }))
      } catch (err) {
        const aborted = controller.signal.aborted
        updateMessage(convId, assistant.id, (m) => ({
          ...m,
          streaming: false,
          error: aborted ? undefined : String((err as Error).message ?? err),
          parts: aborted ? [...(m.parts ?? []), { kind: 'notice', text: 'Stopped.' }] : m.parts,
        }))
      } finally {
        setBusy(false)
        abortRef.current = null
      }
    },
    [active, busy, draft, updateMessage],
  )

  return {
    conversations, active, activeId, setActiveId, newConversation, deleteConversation, send, stop, busy, options, setOptions,
  }
}
