/**
 * Slash commands in the chat, like Discord – shortcuts to things OfficeHub can already do (no bots).
 * Type "/" at the start of a message to see them.
 */

export interface SlashCommand {
  name: string // what is typed after the slash (German and English work)
  aliases: string[]
  icon: string
  takesText?: boolean
}

export const SLASH_COMMANDS: SlashCommand[] = [
  { name: 'umfrage', aliases: ['poll'], icon: 'chart', takesText: true },
  { name: 'anruf', aliases: ['call'], icon: 'video' },
  { name: 'meeting', aliases: ['termin'], icon: 'calendar' },
  { name: 'status', aliases: [], icon: 'user', takesText: true },
  { name: 'nichtstoeren', aliases: ['dnd'], icon: 'bell' },
  { name: 'weg', aliases: ['away', 'brb'], icon: 'clock' },
  { name: 'da', aliases: ['available', 'online'], icon: 'check' },
  { name: 'urlaub', aliases: ['vacation'], icon: 'sun' },
  { name: 'homeoffice', aliases: ['remote'], icon: 'home' },
  { name: 'raum', aliases: ['room'], icon: 'door' },
  { name: 'aufgabe', aliases: ['task'], icon: 'kanban' },
]

/** The command being typed ("/umf" → matches), or null when the text is not a command. */
export function slashMatches(text: string): SlashCommand[] {
  const match = text.match(/^\/([\p{L}]*)$/u)
  if (!match) return []
  const typed = match[1].toLowerCase()
  return SLASH_COMMANDS.filter((c) => [c.name, ...c.aliases].some((n) => n.startsWith(typed)))
}

/** "/status Bin beim Kunden" → { command, rest } */
export function parseSlash(text: string): { command: SlashCommand; rest: string } | null {
  const match = text.trim().match(/^\/([\p{L}]+)\s*([\s\S]*)$/u)
  if (!match) return null
  const typed = match[1].toLowerCase()
  const command = SLASH_COMMANDS.find((c) => c.name === typed || c.aliases.includes(typed))
  return command ? { command, rest: match[2].trim() } : null
}
