import { useState, type FormEvent } from 'react'
import { LoaderCircle, Search } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { api, type DocCard } from '@/lib/api'
import { HitRow, MentionsChart } from './tool-call'

type Mode = 'semantic' | 'exact'

/** Direct access to the archive without the LLM: hybrid search, or exact-phrase counts over time. */
export function ResearchView() {
  const [mode, setMode] = useState<Mode>('semantic')
  const [q, setQ] = useState('')
  const [source, setSource] = useState('all')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [hits, setHits] = useState<DocCard[] | null>(null)
  const [mentions, setMentions] = useState<{ total: number; by_year: Record<string, number>; samples: DocCard[] } | null>(null)

  const run = async (e: FormEvent) => {
    e.preventDefault()
    if (!q.trim()) return
    setLoading(true)
    setError(null)
    try {
      if (mode === 'semantic') {
        setMentions(null)
        setHits((await api.search({ q, source, date_from: from, date_to: to, limit: 30 })).hits)
      } else {
        setHits(null)
        setMentions(await api.mentions(q, source))
      }
    } catch (err) {
      setError(String((err as Error).message))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <form onSubmit={run} className="mx-auto w-full max-w-3xl space-y-3 px-4 pt-6 pb-4">
        <Tabs value={mode} onValueChange={(v) => setMode(v as Mode)}>
          <TabsList>
            <TabsTrigger value="semantic">Hybrid search</TabsTrigger>
            <TabsTrigger value="exact">Exact phrase · counts</TabsTrigger>
          </TabsList>
        </Tabs>
        <div className="flex gap-2">
          <div className="relative flex-1">
            <Search className="absolute start-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              dir="auto"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder={mode === 'semantic' ? 'e.g. دولت و مالیات, or "thoughts on taxation"' : 'e.g. آخوند'}
              className="ps-9"
            />
          </div>
          <Button type="submit" disabled={loading || !q.trim()}>
            {loading ? <LoaderCircle className="animate-spin" /> : 'Search'}
          </Button>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <Select value={source} onValueChange={setSource}>
            <SelectTrigger size="sm" className="w-40">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All sources</SelectItem>
              <SelectItem value="telegram">Telegram</SelectItem>
              <SelectItem value="weblog">Weblog</SelectItem>
            </SelectContent>
          </Select>
          {mode === 'semantic' && (
            <>
              <Input value={from} onChange={(e) => setFrom(e.target.value)} placeholder="From (YYYY)" className="h-8 w-32" />
              <Input value={to} onChange={(e) => setTo(e.target.value)} placeholder="To (YYYY)" className="h-8 w-32" />
            </>
          )}
        </div>
      </form>
      <div className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto">
        <div className="mx-auto w-full max-w-3xl space-y-2 px-4 pb-10">
          {error && <p className="text-sm text-destructive">{error}</p>}
          {hits && (hits.length ? hits.map((d) => <HitRow key={d.id} doc={d} lines={4} />) : <Empty />)}
          {mentions && (mentions.total ? <MentionsChart total={mentions.total} byYear={mentions.by_year} samples={mentions.samples} /> : <Empty />)}
          {!hits && !mentions && !error && (
            <p className="pt-8 text-center text-sm text-muted-foreground">
              Search the raw archive directly — useful for checking what the agent cites, or for collecting evidence.
            </p>
          )}
        </div>
      </div>
    </div>
  )
}

const Empty = () => <p className="pt-8 text-center text-sm text-muted-foreground">No results.</p>
