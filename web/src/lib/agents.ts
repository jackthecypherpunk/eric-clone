import { Drama, Microscope, type LucideIcon } from 'lucide-react'

export type AgentId = 'clone' | 'analyst'

export interface AgentMeta {
  id: AgentId
  label: string
  tagline: (persona: string) => string
  icon: LucideIcon
  /** classes for small badges/icons (tinted background + readable foreground in both themes) */
  tint: string
  /** solid avatar classes */
  solid: string
  suggestions: string[]
}

export const AGENTS: Record<AgentId, AgentMeta> = {
  clone: {
    id: 'clone',
    label: 'Clone',
    tagline: (p) => `Talk to ${p} himself. Answers in his voice, from his own writing.`,
    icon: Drama,
    tint: 'bg-amber-500/15 text-amber-700 dark:text-amber-300',
    solid: 'bg-amber-500 text-white dark:bg-amber-400 dark:text-amber-950',
    suggestions: [
      'نظرت درباره دولت و مالیات چیه؟',
      'What do you think about the 2022 protests?',
      'از کی و چند بار درباره «آخوند» نوشتی؟',
      'Your blog years vs. now: what changed in how you see religion?',
    ],
  },
  analyst: {
    id: 'analyst',
    label: 'Analyst',
    tagline: (p) => `A researcher who studies ${p}: his ideas, rhetoric and how they changed. Never imitates him.`,
    icon: Microscope,
    tint: 'bg-sky-500/15 text-sky-700 dark:text-sky-300',
    solid: 'bg-sky-600 text-white dark:bg-sky-400 dark:text-sky-950',
    suggestions: [
      'What are the main themes of his writing, and how did they change over time?',
      'چه تکنیک‌های طنزی در «اقوال الانعام» به کار می‌بره؟',
      'How consistent are his economic views? Find contradictions.',
      'Compare his weblog essays with his Telegram posts.',
    ],
  },
}

export const AGENT_LIST = Object.values(AGENTS)
