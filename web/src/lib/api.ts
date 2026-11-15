export type SourceType = 'telegram' | 'weblog'

export interface DocCard {
  id: string
  source: string
  source_type: SourceType
  date: string
  title: string
  text: string
  pages: string
  message_id: number | null
  score?: number
  relation?: 'replied to' | 'before' | 'after'
}

export interface Status {
  ready: boolean
  persona: string
  corpus: { documents: number; by_source: Record<string, number>; date_range: [string, string] | null }
  vectors: number
  embed_model: string
  rerank: string | null
  llm: LLMSettings
}

export type SearchProvider = 'auto' | 'tavily' | 'brave' | 'duckduckgo'

export interface LLMSettings {
  base_url: string
  model: string
  temperature: number
  max_tokens: number
  has_api_key: boolean
  api_key_hint: string
  search_provider: SearchProvider
  has_search_api_key: boolean
  search_api_key_hint: string
}

export interface Attachment {
  id: string
  name: string
  size: number
  kind: 'image' | 'pdf' | 'document' | 'text'
  pages?: number
  chars?: number
  truncated?: boolean
  warning?: string
}

export interface WebResult {
  title: string
  url: string
  snippet: string
  date: string
}

export type AgentEvent =
  | { type: 'reasoning'; text: string }
  | { type: 'token'; text: string }
  | { type: 'tool_call'; id: string; name: string; arguments: Record<string, unknown> | string }
  | { type: 'tool_result'; id: string; name: string; summary: string; data: ToolData; elapsed_ms: number }
  | { type: 'notice'; message: string }
  | { type: 'done'; elapsed_ms: number; usage: { prompt_tokens?: number; completion_tokens?: number } }
  | { type: 'error'; message: string }

export interface ToolData {
  error?: string
  hits?: DocCard[]
  document?: DocCard
  context?: DocCard[]
  total?: number
  by_year?: Record<string, number>
  samples?: DocCard[]
  results?: WebResult[]
  provider?: string
  page?: { title: string; url: string; excerpt: string }
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail ?? body)
    } catch {
      /* not JSON */
    }
    throw new Error(detail)
  }
  return res.json() as Promise<T>
}

export const api = {
  status: () => fetch('/api/status').then(json<Status>),

  saveLLM: (body: {
    base_url: string
    model: string
    temperature: number
    max_tokens?: number
    api_key?: string
    search_provider?: SearchProvider
    search_api_key?: string
  }) =>
    fetch('/api/settings/llm', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(json<LLMSettings>),

  models: (body: { base_url?: string; api_key?: string }) =>
    fetch('/api/settings/models', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(json<{ models: string[]; error?: string }>),

  document: (id: string) =>
    fetch(`/api/documents/${encodeURIComponent(id)}`).then(json<{ document: DocCard; context: DocCard[] }>),

  search: (params: { q: string; source?: string; date_from?: string; date_to?: string; limit?: number }) => {
    const qs = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => v !== undefined && v !== '' && qs.set(k, String(v)))
    return fetch(`/api/search?${qs}`).then(json<{ hits: DocCard[] }>)
  },

  upload: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return fetch('/api/attachments', { method: 'POST', body: form }).then(json<Attachment>)
  },

  imageUrl: (id: string) => `/api/attachments/${id}/image`,

  mentions: (phrase: string, source = 'all') =>
    fetch(`/api/mentions?${new URLSearchParams({ phrase, source })}`).then(
      json<{ total: number; by_year: Record<string, number>; samples: DocCard[] }>,
    ),
}

/** POSTs the conversation and yields agent events as they stream in (Server-Sent Events). */
export async function* streamChat(
  messages: { role: 'user' | 'assistant'; content: string; attachments?: string[] }[],
  options: { agent: 'clone' | 'analyst'; web_search: boolean },
  signal: AbortSignal,
): AsyncGenerator<AgentEvent> {
  const res = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages, ...options }),
    signal,
  })
  if (!res.ok || !res.body) {
    await json(res)
    return
  }
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += value
    let sep: number
    while ((sep = buffer.indexOf('\n\n')) !== -1) {
      const frame = buffer.slice(0, sep)
      buffer = buffer.slice(sep + 2)
      const data = frame
        .split('\n')
        .filter((l) => l.startsWith('data:'))
        .map((l) => l.slice(5).trimStart())
        .join('\n')
      if (data) yield JSON.parse(data) as AgentEvent
    }
  }
}
