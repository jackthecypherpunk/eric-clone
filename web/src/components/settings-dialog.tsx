import { useEffect, useState, type FocusEvent } from 'react'
import { LoaderCircle, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Slider } from '@/components/ui/slider'
import { Separator } from '@/components/ui/separator'
import { api, type LLMSettings, type SearchProvider } from '@/lib/api'

const PRESETS = [
  { id: 'ollama', label: 'Ollama (local)', url: 'http://localhost:11434/v1', key: false },
  { id: 'lmstudio', label: 'LM Studio (local)', url: 'http://localhost:1234/v1', key: false },
  { id: 'openai', label: 'OpenAI', url: 'https://api.openai.com/v1', key: true },
  { id: 'openrouter', label: 'OpenRouter', url: 'https://openrouter.ai/api/v1', key: true },
  { id: 'anthropic', label: 'Anthropic (OpenAI-compatible)', url: 'https://api.anthropic.com/v1', key: true },
  { id: 'custom', label: 'Custom OpenAI-compatible', url: '', key: true },
] as const

const SEARCH_PROVIDERS: { id: SearchProvider; label: string; hint: string }[] = [
  { id: 'auto', label: 'Automatic', hint: 'Tavily or Brave if a key is set (detected from the key), otherwise DuckDuckGo.' },
  { id: 'tavily', label: 'Tavily (best for agents)', hint: 'Free tier at tavily.com. Returns clean article text.' },
  { id: 'brave', label: 'Brave Search', hint: 'Free tier at brave.com/search/api.' },
  { id: 'duckduckgo', label: 'DuckDuckGo (no key)', hint: 'Free and keyless, but rate-limited and less thorough.' },
]

/**
 * A secret field that shows a masked version of the stored key instead of being blank.
 * Returns undefined from `toSubmit` when the user didn't touch it, so the server keeps the stored key.
 */
function useSecret(hint: string) {
  const [value, setValue] = useState(hint)
  const [touched, setTouched] = useState(false)
  return {
    value,
    reset: (h: string) => {
      setValue(h)
      setTouched(false)
    },
    onChange: (v: string) => {
      setValue(v)
      setTouched(true)
    },
    // Typing into a masked field replaces the whole mask.
    onFocus: (e: FocusEvent<HTMLInputElement>) => !touched && hint && e.target.select(),
    toSubmit: () => (touched ? value : undefined),
    /** the key to use for a live request (model list): only a freshly typed one */
    fresh: () => (touched && value ? value : undefined),
  }
}

const presetFor = (url: string) => PRESETS.find((p) => p.url && url.startsWith(p.url))?.id ?? 'custom'

export function SettingsDialog({
  open,
  onOpenChange,
  current,
  onSaved,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  current: LLMSettings | undefined
  onSaved: (s: LLMSettings) => void
}) {
  const [preset, setPreset] = useState<string>('ollama')
  const [baseUrl, setBaseUrl] = useState('')
  const [model, setModel] = useState('')
  const apiKey = useSecret(current?.api_key_hint ?? '')
  const searchKey = useSecret(current?.search_api_key_hint ?? '')
  const [searchProvider, setSearchProvider] = useState<SearchProvider>('auto')
  const [temperature, setTemperature] = useState(0.6)
  const [maxTokens, setMaxTokens] = useState(8192)
  const [models, setModels] = useState<string[]>([])
  const [loadingModels, setLoadingModels] = useState(false)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!open || !current) return
    setBaseUrl(current.base_url)
    setModel(current.model)
    setTemperature(current.temperature)
    setMaxTokens(current.max_tokens ?? 8192)
    setPreset(presetFor(current.base_url))
    apiKey.reset(current.api_key_hint)
    searchKey.reset(current.search_api_key_hint)
    setSearchProvider(current.search_provider)
    setModels([])
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, current])

  const fetchModels = async () => {
    setLoadingModels(true)
    try {
      const res = await api.models({ base_url: baseUrl, api_key: apiKey.fresh() })
      setModels(res.models)
      if (res.error) toast.error(res.error)
      else if (!res.models.length) toast.message('The endpoint returned no models.')
    } catch (e) {
      toast.error(String((e as Error).message))
    } finally {
      setLoadingModels(false)
    }
  }

  const save = async () => {
    setSaving(true)
    try {
      const saved = await api.saveLLM({
        base_url: baseUrl,
        model,
        temperature,
        max_tokens: maxTokens,
        api_key: apiKey.toSubmit(),
        search_provider: searchProvider,
        search_api_key: searchKey.toSubmit(),
      })
      onSaved(saved)
      toast.success(`Using ${saved.model}`)
      onOpenChange(false)
    } catch (e) {
      toast.error(String((e as Error).message))
    } finally {
      setSaving(false)
    }
  }

  const presetInfo = PRESETS.find((p) => p.id === preset)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Model</DialogTitle>
          <DialogDescription>
            Any OpenAI-compatible endpoint works, local or cloud. Pick a model that supports tool calling (e.g.
            qwen3, llama3.1+, gpt-4.1, claude) so the agent can search the archive itself.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4">
          <div className="grid gap-2">
            <Label>Provider</Label>
            <Select
              value={preset}
              onValueChange={(v) => {
                setPreset(v)
                const p = PRESETS.find((x) => x.id === v)
                if (p?.url) setBaseUrl(p.url)
                // A saved key belongs to the saved endpoint: don't carry it over to another provider.
                if (p?.url && current && p.url !== current.base_url) apiKey.onChange('')
                else if (current) apiKey.reset(current.api_key_hint)
                setModels([])
              }}
            >
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PRESETS.map((p) => (
                  <SelectItem key={p.id} value={p.id}>
                    {p.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="base-url">Base URL</Label>
            <Input id="base-url" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://…/v1" />
          </div>
          {presetInfo?.key !== false && (
            <div className="grid gap-2">
              <Label htmlFor="api-key">API key</Label>
              <Input
                id="api-key"
                type={apiKey.value === current?.api_key_hint ? 'text' : 'password'}
                autoComplete="off"
                spellCheck={false}
                value={apiKey.value}
                onFocus={apiKey.onFocus}
                onChange={(e) => apiKey.onChange(e.target.value)}
                placeholder="sk-…"
                className="font-mono"
              />
              {current?.has_api_key && (
                <p className="text-xs text-muted-foreground">A key is saved. Type to replace it, or clear the field to remove it.</p>
              )}
            </div>
          )}
          <div className="grid gap-2">
            <Label htmlFor="model">Model</Label>
            <div className="flex gap-2">
              <Input id="model" list="model-options" value={model} onChange={(e) => setModel(e.target.value)} placeholder="qwen3:8b" />
              <datalist id="model-options">
                {models.map((m) => (
                  <option key={m} value={m} />
                ))}
              </datalist>
              <Button variant="outline" size="icon" onClick={fetchModels} disabled={loadingModels || !baseUrl} aria-label="Load models">
                {loadingModels ? <LoaderCircle className="animate-spin" /> : <RefreshCw />}
              </Button>
            </div>
            {models.length > 0 && <p className="text-xs text-muted-foreground">{models.length} models available — start typing to filter.</p>}
          </div>
          <div className="grid gap-3">
            <div className="flex items-center justify-between">
              <Label>Temperature</Label>
              <span className="text-sm text-muted-foreground tabular-nums">{temperature.toFixed(2)}</span>
            </div>
            <Slider min={0} max={1.2} step={0.05} value={[temperature]} onValueChange={([v]) => setTemperature(v)} />
            <p className="text-xs text-muted-foreground">Lower is more literal to the sources; higher is more playful.</p>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="max-tokens">Max answer length (tokens)</Label>
            <Select value={String(maxTokens)} onValueChange={(v) => setMaxTokens(Number(v))}>
              <SelectTrigger id="max-tokens" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {[1024, 2048, 4096, 8192, 16384, 32768, 65536, 0].map((n) => (
                  <SelectItem key={n} value={String(n)}>
                    {n === 0 ? 'No limit' : n.toLocaleString()}
                    {n === 8192 ? ' (recommended)' : ''}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              Caps each reply, including a thinking model's hidden reasoning (DeepSeek, Qwen3, o-series…), which can
              use thousands of tokens before the answer starts. "No limit" lets the model decide, but some providers
              (e.g. OpenRouter) then reserve credit for the model's full maximum and may refuse when your balance is low.
            </p>
          </div>
          <Separator />
          <div className="grid gap-2">
            <Label>Web search</Label>
            <Select value={searchProvider} onValueChange={(v) => setSearchProvider(v as SearchProvider)}>
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SEARCH_PROVIDERS.map((p) => (
                  <SelectItem key={p.id} value={p.id}>
                    {p.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              {SEARCH_PROVIDERS.find((p) => p.id === searchProvider)?.hint} Turn it on per chat with the Web button.
            </p>
          </div>
          {searchProvider !== 'duckduckgo' && (
            <div className="grid gap-2">
              <Label htmlFor="search-key">Search API key</Label>
              <Input
                id="search-key"
                type={searchKey.value === current?.search_api_key_hint ? 'text' : 'password'}
                autoComplete="off"
                spellCheck={false}
                value={searchKey.value}
                onFocus={searchKey.onFocus}
                onChange={(e) => searchKey.onChange(e.target.value)}
                placeholder={searchProvider === 'auto' ? 'Optional: tvly-… or a Brave key' : 'API key'}
                className="font-mono"
              />
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={save} disabled={saving || !baseUrl || !model}>
            {saving && <LoaderCircle className="animate-spin" />} Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
