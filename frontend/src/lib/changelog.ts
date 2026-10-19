/** "What's new" entries in plain language. Newest first. */

export interface ChangelogEntry {
  version: string
  date: string
  de: string[]
  en: string[]
}

export const CHANGELOG: ChangelogEntry[] = [
  {
    version: '1.1.0',
    date: '2026-10-19',
    de: [
      'Kollegium: Kolleginnen und Kollegen suchen, Organigramm und Telefonliste.',
      'Besprechungsräume einfach für einen Zeitraum buchen.',
      'Besuch anmelden – der Empfang sieht alle Gäste des Tages.',
      'Neue Anfrage: Termin mit HR, IT oder der Führungskraft vorschlagen.',
      'Mitarbeitergespräche gemeinsam vorbereiten und Ziele bestätigen.',
      'Einarbeitung: Checkliste für neue Kolleginnen und Kollegen.',
      'Weitere Tools im Menü, einstellbare Schnellzugriffe und Ansprechpersonen pro Bereich.',
      'Berichte für Führungskräfte mit CSV-Export.',
    ],
    en: [
      'People: find colleagues, see the org chart and the phone list.',
      'Book meeting rooms for a time slot.',
      'Register visitors – reception sees all guests of the day.',
      'New request: suggest an appointment with HR, IT or your manager.',
      'Prepare employee reviews together and confirm the agreed goals.',
      'Onboarding: a checklist for new colleagues.',
      'More tools in the menu, configurable quick actions and contact people per section.',
      'Reports for managers with CSV export.',
    ],
  },
  {
    version: '1.0.0',
    date: '2026-10-18',
    de: ['Erste Version: Anträge, Freigaben, Dokumente, Neuigkeiten und Profil.'],
    en: ['First version: requests, approvals, documents, announcements and profile.'],
  },
]
