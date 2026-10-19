/** "What's new" entries in plain language. Newest first. */

export interface ChangelogEntry {
  version: string
  date: string
  de: string[]
  en: string[]
}

export const CHANGELOG: ChangelogEntry[] = [
  {
    version: '2.0.0',
    date: '2026-10-19',
    de: [
      'Neues, ruhigeres Design mit besser lesbarer Schrift – hell und dunkel, auch am Handy.',
      'Eine Suche für alles: oben auf „Suchen“ klicken oder Strg+K drücken.',
      'Benachrichtigungen: Die Glocke zeigt, wenn dein Antrag geprüft, genehmigt oder kommentiert wurde oder dein Besuch da ist.',
      'Neue Startseite: wichtige Neuigkeit, Zahlen auf einen Blick, „Braucht deine Aufmerksamkeit“ und letzte Aktivitäten.',
      'Zähler im Menü zeigen offene Freigaben, Gäste heute und Gespräche zum Vorbereiten.',
      'Wichtige Mitteilungen mit Lesebestätigung – HR sieht, wer schon gelesen hat, und kann erinnern.',
      'Kleine Umfragen unter Neuigkeiten.',
      'Wer ist nicht da? Urlaub und Homeoffice der nächsten Tage – ohne Gründe.',
      'Gemeinsam feiern: Geburtstage (freiwillig), Jubiläen und neue Kolleginnen und Kollegen.',
      'Urlaubskonto: Beim Urlaubsantrag siehst du, wie viele Tage noch frei sind.',
      'Schreibtische und Parkplätze für den Vormittag, Nachmittag oder ganzen Tag buchen.',
      'Persönliche Dokumente: Das HR-Team kann dir z. B. Gehaltsabrechnungen sicher bereitstellen.',
      'Teamkalender mit Abteilungsfilter und Export für Outlook & Co.',
      'Hilfe & FAQ mit Suche und „War das hilfreich?“.',
      'Was gibt’s Neues im Unternehmen? Neuigkeiten, Dokumente und Jubiläen auf der Startseite.',
    ],
    en: [
      'A calmer new design with easier-to-read text – light and dark, on phones too.',
      'One search for everything: click "Search" at the top or press Ctrl+K.',
      'Notifications: the bell tells you when your request is being looked at, approved or commented on, or when your visitor has arrived.',
      'New home page: important news, numbers at a glance, "Needs your attention" and recent activity.',
      'Counters in the menu show open approvals, visitors today and reviews to prepare.',
      'Important announcements with read confirmation – HR sees who has read them and can send a reminder.',
      'Small polls under announcements.',
      'Who is away? Vacation and working from home for the next days – without reasons.',
      'Let’s celebrate: birthdays (optional), work anniversaries and new colleagues.',
      'Vacation balance: the vacation form shows how many days you have left.',
      'Book desks and parking spaces for the morning, afternoon or whole day.',
      'Personal documents: the HR team can share payslips and similar files with you securely.',
      'Team calendar with a department filter and export for Outlook and other calendars.',
      'Help & FAQ with search and "Was this helpful?".',
      'What’s new in the company? News, documents and anniversaries on the home page.',
    ],
  },
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
