export type Role = 'employee' | 'manager' | 'admin'
export type Language = 'de' | 'en'

export type RequestType = 'vacation' | 'home_office' | 'equipment' | 'expense' | 'it_access' | 'appointment' | 'general'
export type RequestStatus = 'draft' | 'submitted' | 'in_review' | 'approved' | 'rejected' | 'cancelled'

export interface User {
  id: number
  email: string
  first_name: string
  last_name: string
  full_name: string
  department: string
  job_title: string
  office_location: string
  language: Language
  role: Role
  is_active: boolean
  phone: string
  mobile: string
  show_phone: boolean
  show_mobile: boolean
  manager_id: number | null
  pinned_tiles: string[]
  start_date: string | null
  birthday_day: number | null
  birthday_month: number | null
  show_birthday: boolean
  vacation_days: number
  weekly_minutes: number
  photo_version: string | null
  deputy_id: number | null
  deputy_until: string | null
  totp_enabled: boolean
  email_notifications: boolean
  e2ee_required?: boolean
}

export interface UserBrief {
  id: number
  full_name: string
  department: string
  photo_version?: string | null
}

export interface RequestComment {
  id: number
  body: string
  author: UserBrief
  created_at: string
}

export interface RequestEvent {
  id: number
  action: string
  actor: UserBrief
  created_at: string
}

export interface RequestPermissions {
  can_edit: boolean
  can_submit: boolean
  can_cancel: boolean
  can_comment: boolean
  can_decide: boolean
  can_start_review: boolean
  can_attach: boolean
}

export interface OfficeRequest {
  id: number
  type: RequestType
  title: string
  description: string
  status: RequestStatus
  requester: UserBrief
  start_date: string | null
  end_date: string | null
  working_days: number | null
  amount: string | null
  currency: string | null
  category: string | null
  item: string | null
  access_level: string | null
  needed_by: string | null
  proposed_times: string[] | null
  confirmed_time: string | null
  attachment_name: string | null
  decision_comment: string | null
  decided_by: UserBrief | null
  decided_at: string | null
  submitted_at: string | null
  created_at: string
  updated_at: string
  comment_count: number
}

export interface RequestDetail extends OfficeRequest {
  comments: RequestComment[]
  events: RequestEvent[]
  permissions: RequestPermissions
}

export interface RequestList {
  items: OfficeRequest[]
  total: number
}

export interface Announcement {
  id: number
  title: string
  body: string
  category: string
  publish_date: string
  expiry_date: string | null
  event_date: string | null
  pinned: boolean
  archived: boolean
  must_read: boolean
  confirmed_at: string | null
  poll: Poll | null
  author: UserBrief
  created_at: string
  updated_at: string
}

export interface OfficeDocument {
  id: number
  title: string
  description: string
  category: string
  file_name: string
  file_type: 'pdf' | 'md' | 'txt' | 'docx'
  file_size: number
  archived: boolean
  created_at: string
  updated_at: string
  snippet: string | null
}

export interface Stats {
  pending: number
  by_status: Record<string, number>
  pending_by_type: Record<RequestType, number>
  decided_this_month: number
  average_decision_hours: number | null
  approved_vacation_days_this_year: number
  active_employees: number
}

export interface DemoAccount {
  email: string
  name: string
  department: string
  role: Role
}

export interface PublicConfig {
  version?: string
  demo_mode: boolean
  max_upload_mb: number
  demo_accounts?: DemoAccount[]
  demo_password?: string
  mail_enabled?: boolean
  meetings_enabled?: boolean
  /** Company login (Authentik, Keycloak …) is set up; label = how HR named it */
  sso?: { label: string }
}

export interface DirectoryEntry {
  id: number
  first_name: string
  last_name: string
  full_name: string
  department: string
  job_title: string
  office_location: string
  email: string
  phone: string
  mobile: string
  manager_id: number | null
  photo_version?: string | null
}

export type ResourceKind = 'room' | 'desk' | 'parking'

export interface Room {
  id: number
  kind: ResourceKind
  name: string
  seats: number
  equipment: string
  active: boolean
}

export interface Booking {
  id: number
  room_id: number
  room_name: string
  room_kind: ResourceKind
  day: string
  start_time: string
  end_time: string
  title: string
  person_id: number
  person_name: string
  can_cancel: boolean
}

export type VisitorStatus = 'expected' | 'checked_in' | 'checked_out' | 'cancelled'

export interface Visitor {
  id: number
  name: string
  company: string
  visit_date: string
  expected_time: string
  note: string
  status: VisitorStatus
  host_id: number
  host_name: string
  checked_in_at: string | null
  checked_out_at: string | null
  can_cancel: boolean
  can_check_in: boolean
}

export interface Review {
  id: number
  year: number
  status: 'preparation' | 'completed'
  employee: UserBrief
  reviewer: UserBrief
  meeting_date: string | null
  my_side: 'employee' | 'reviewer' | 'hr'
  employee_prep_done: boolean
  reviewer_prep_done: boolean
  employee_prep: Record<string, string> | null
  reviewer_prep: Record<string, string> | null
  goals: string
  employee_confirmed_at: string | null
  reviewer_confirmed_at: string | null
  updated_at: string
}

export interface OnboardingTask {
  id: number
  key: string | null
  title: string
  owner: 'hr' | 'it' | 'manager'
  done: boolean
  done_at: string | null
  done_by: string | null
  can_toggle: boolean
}

export interface Checklist {
  person: UserBrief
  kind: 'onboarding' | 'offboarding'
  last_day: string | null
  manager_name: string | null
  total: number
  done: number
  tasks: OnboardingTask[]
}

export interface ChecklistSummary {
  person: UserBrief
  kind: 'onboarding' | 'offboarding'
  last_day: string | null
  total: number
  done: number
}

export interface QuickLink {
  id: number
  title: string
  url: string
  icon: string
  description: string
  sort_order: number
  active: boolean
}

export interface SectionContact {
  id: number
  full_name: string
  email: string
  phone: string
}

export interface PortalSettings {
  dashboard_tiles: string[]
  section_contacts: Partial<Record<string, SectionContact>>
  require_2fa_roles?: Role[]
}

export interface Report {
  name: string
  columns: string[]
  rows: (string | number | null)[][]
}

export interface AppNotification {
  id: number
  kind: string
  params: Record<string, string | number>
  link: string
  read: boolean
  created_at: string
}

export interface NotificationList {
  items: AppNotification[]
  unread: number
}

export interface Summary {
  unread: number
  approvals_pending: number
  reviews_todo: number
  visitors_today: number
  must_read_open: number
  personal_documents_new: number
  acting_deputy: boolean
  trainings_due: number
  surveys_open: number
  time_months_pending: number
  chat_unread: number
  cards_due: number
  presence?: Presence
  reminders: { meeting_id: number; title: string; starts_at: string; ends_at: string }[]
  version?: string
  devices_pending?: number
}

export interface SearchHit {
  id: number
  title: string
  subtitle: string
  link: string
}

export interface SearchResults {
  people: DirectoryEntry[]
  documents: SearchHit[]
  announcements: SearchHit[]
  requests: SearchHit[]
  links: SearchHit[]
  workspace: SearchHit[]
}

export interface Poll {
  question: string
  options: string[]
  my_vote: number | null
  counts: number[] | null
  total: number
}

export interface Reader {
  id: number
  full_name: string
  department: string
  read_at: string | null
}

export interface Confirmations {
  confirmed: Reader[]
  missing: Reader[]
}

export interface Absence {
  person: UserBrief
  type: 'vacation' | 'home_office'
  start_date: string
  end_date: string
}

export interface Celebration {
  person: UserBrief
  kind: 'birthday' | 'anniversary' | 'new'
  date: string
  years: number | null
}

export interface TeamCalendar {
  month: string
  absences: Absence[]
  events: { title: string; date: string; link: string }[]
  birthdays: Celebration[]
}

export interface VacationBalance {
  year: number
  entitlement: number
  taken: number
  planned: number
  remaining: number
}

export interface ActivityItem {
  kind: 'announcement' | 'document' | 'new_colleague' | 'anniversary'
  title: string
  date: string
  link: string
  years: number | null
}

export interface PersonalDocument {
  id: number
  title: string
  file_name: string
  file_type: string
  file_size: number
  created_at: string
  opened_at: string | null
  person: UserBrief
  uploaded_by: UserBrief
}

export interface HelpArticle {
  id: number
  section: string
  question: string
  answer: string
  sort_order: number
  active: boolean
  helpful_yes: number
  helpful_no: number
  updated_at: string
}

export interface TimeEntry {
  id: number
  day: string
  start_at: string
  end_at: string | null
  minutes: number
  note: string
  edited: boolean
  project_id: number | null
  project_name: string | null
}

export interface TimeDay {
  date: string
  entries: TimeEntry[]
  worked: number
  target: number
  off: string | null
  warnings: string[]
  pending: string | null
  home_office: boolean
}

export interface TimeMonth {
  person: UserBrief
  month: string
  days: TimeDay[]
  worked: number
  target: number
  balance_year: number
  vacation: { entitlement: number; taken: number; planned: number; remaining: number }
  status: 'open' | 'submitted' | 'approved' | 'returned'
  comment: string
  decided_by: string | null
  decided_at: string | null
  submitted_at: string | null
  can_submit: boolean
  can_decide: boolean
}

export interface PendingMonth {
  person: UserBrief
  month: string
  worked: number
  target: number
  submitted_at: string
}

export interface TimeWeek {
  person: UserBrief
  start: string
  days: TimeDay[]
  worked: number
  target: number
  balance_year: number
}

export interface TimeStatus {
  running: TimeEntry | null
  today_worked: number
  today_target: number
  week_worked: number
  week_target: number
  balance_year: number
}

export interface TimeTeamRow {
  person: UserBrief
  worked: number
  target: number
  clocked_in: boolean
}

export interface AssetEvent {
  action: string
  person_name: string | null
  actor_name: string
  note: string
  created_at: string
}

export interface Asset {
  id: number
  name: string
  kind: string
  serial: string
  notes: string
  status: 'in_stock' | 'assigned' | 'repair' | 'retired'
  assigned_to: UserBrief | null
  assigned_at: string | null
  history: AssetEvent[]
}

export interface SurveyQuestion {
  text: string
  kind: 'scale' | 'choice' | 'text'
  options: string[]
}

export interface Survey {
  id: number
  title: string
  intro: string
  questions: SurveyQuestion[]
  status: 'draft' | 'open' | 'closed'
  closes_on: string | null
  results_public: boolean
  answered: boolean
  responses: number
  can_see_results: boolean
}

export interface SurveyResults {
  survey: Survey
  responses: number
  enough: boolean
  questions: (SurveyQuestion & { counts: number[]; average: number | null; texts: string[] })[]
}

export type IdeaStatus = 'new' | 'review' | 'planned' | 'done' | 'declined'

export interface Idea {
  id: number
  title: string
  body: string
  author: UserBrief
  status: IdeaStatus
  response: string
  votes: number
  voted: boolean
  can_delete: boolean
  created_at: string
  updated_at: string
}

export interface Training {
  id: number
  title: string
  description: string
  interval_months: number | null
  due_within_days: number
  department: string
  link: string
  active: boolean
}

export interface TrainingStatus {
  training: Training
  person: UserBrief
  status: 'open' | 'due_soon' | 'overdue' | 'valid' | 'expiring'
  due_on: string | null
  completed_on: string | null
  valid_until: string | null
  record_id: number | null
  has_certificate: boolean
}

export interface Project {
  id: number
  name: string
  client: string
  color: string
  budget_minutes: number | null
  start_date: string | null
  end_date: string | null
  active: boolean
  planned_minutes: number | null
  booked_minutes: number | null
}

export interface Allocation {
  id: number
  project_id: number
  user_id: number
  start_date: string
  end_date: string
  minutes_per_day: number
  note: string
}

export interface PlanningRow {
  person: UserBrief
  editable: boolean
  away: string[]
  capacity: number
  planned: number
  booked: number
}

export interface PlanningBoard {
  start: string
  end: string
  days: { date: string; off: 'weekend' | 'holiday' | null }[]
  rows: PlanningRow[]
  allocations: Allocation[]
  projects: Project[]
  can_plan: boolean
}

export interface ProjectReport {
  project: Project
  rows: { person: UserBrief; planned: number; booked: number }[]
  weeks: { start: string; planned: number; booked: number }[]
}

export interface MyAllocation {
  id: number
  project: Project
  start_date: string
  end_date: string
  minutes_per_day: number
  note: string
}

export interface Space {
  id: number
  name: string
  description: string
  color: string
  project_id: number | null
  archived: boolean
  my_role: 'manager' | 'member' | null
  member_count: number
  file_count: number
  open_cards: number
  unread: number
  updated_at: string | null
}

export interface SpaceDetail extends Space {
  members: { person: UserBrief; role: 'manager' | 'member' }[]
  board_id: number | null
}

export interface Folder {
  id: number
  name: string
  parent_id: number | null
  deleted_at?: string | null
}

export interface SpaceFile {
  id: number
  space_id: number
  folder_id: number | null
  name: string
  file_type: string
  size: number
  version: number
  updated_by: string | null
  updated_at: string
  deleted_at?: string | null
  locked: boolean
  checked_out_by_id?: number | null
  checked_out_by?: string | null
  checked_out_at?: string | null
}

export interface FileVersion {
  number: number
  size: number
  source: 'upload' | 'editor' | 'restore' | 'new' | 'drive' | 'wordcraft' | 'deckcraft'
  created_by: string | null
  created_at: string
}

export interface SpaceFileDetail extends SpaceFile {
  versions: FileVersion[]
  path: Folder[]
  drive_path?: string | null
}

export interface AppPassword {
  id: number
  name: string
  created_at: string
  last_used_at: string | null
}

export interface FileListing {
  folder: Folder | null
  path: Folder[]
  folders: Folder[]
  files: SpaceFile[]
  can_write: boolean
}

export interface SpaceOverview {
  files: SpaceFile[]
  cards: { id: number; title: string; due_date: string | null; column: string; assignees: string[] }[]
  pages: { id: number; title: string; updated_at: string }[]
  activity: { kind: 'file' | 'card' | 'page' | 'message'; title: string; person: string | null; at: string; link: string }[]
}

export interface OfficeConfig {
  engines: ('collabora' | 'onlyoffice')[]
  default: 'collabora' | 'onlyoffice' | null
  editable: Record<string, string[]>
  craft?: ('wordcraft' | 'deckcraft')[]
  prefer_craft?: boolean
}

export interface OfficeOpen {
  engine: 'collabora' | 'onlyoffice'
  can_write: boolean
  file_name: string
  /** Who has it open in WordCraft/DeckCraft or on the network drive ("" = someone), when that is why it is read-only */
  editing_by: string | null
  action_url: string | null
  access_token: string | null
  access_token_ttl: number | null
  script: string | null
  config: Record<string, unknown> | null
}

export interface BoardCard {
  id: number
  column_id: number
  title: string
  position: number
  due_date: string | null
  label: string
  assignees: UserBrief[]
  comment_count: number
  has_description: boolean
}

export interface BoardCardDetail extends BoardCard {
  description: string
  created_at: string
  comments: { id: number; author: UserBrief | null; body: string; created_at: string }[]
}

export interface BoardColumn {
  id: number
  name: string
  position: number
  is_done: boolean
  cards: BoardCard[]
}

export interface Board {
  id: number
  name: string
  space_id: number
  space_name: string
  can_write: boolean
  columns: BoardColumn[]
  members: UserBrief[]
}

export interface MyCard {
  id: number
  title: string
  due_date: string | null
  label: string
  column: string
  space_id: number
  space_name: string
  board_id: number
}

export interface Conversation {
  id: number
  kind: 'channel' | 'direct'
  name: string
  space_id: number | null
  space_name: string | null
  other: UserBrief | null
  unread: number
  last: { body: string; author: string | null; at: string; call?: boolean } | null
  notify?: 'all' | 'mentions' | 'none'
  muted?: boolean
}

export interface ChatMessage {
  id: number
  author: UserBrief | null
  body: string
  file: { id: number; name: string; file_type: string; size: number } | null
  created_at: string
  edited: boolean
  deleted: boolean
  mine: boolean
  meeting?: { id: number; active: boolean } | null
  kind?: 'text' | 'poll' | 'voice'
  parent_id?: number | null
  reply_count?: number
  last_reply_at?: string | null
  reply_people?: string[]
  pinned?: boolean
  reactions?: { emoji: string; count: number; mine: boolean; names: string[] }[]
  poll?: { options: { id: number; text: string; votes: number; mine: boolean; voters: string[] }[]; multi: boolean; closed: boolean; total: number } | null
  audio_seconds?: number | null
}

export interface ChatPage {
  conversation: Conversation
  messages: ChatMessage[]
  members: UserBrief[]
  has_more: boolean
  changed?: ChatMessage[]
  server_time?: string
}

/** What can be done with a message in a thread (handled by the conversation). */
export type MessageAction = 'react' | 'vote' | 'closePoll' | 'edit' | 'remove'

export interface ChatThread {
  parent: ChatMessage
  replies: ChatMessage[]
  server_time: string
}

export interface WikiPageSummary {
  id: number
  title: string
  parent_id: number | null
  updated_at: string
  updated_by: string | null
}

export interface WikiPage extends WikiPageSummary {
  space_id: number
  body: string
  version: number
  editors: UserBrief[]
  can_write: boolean
}

export interface WikiRevision {
  version: number
  title: string
  author: string | null
  created_at: string
  body?: string
}

// ---------- meetings and calls ----------

export interface MeetingPerson {
  person: UserBrief
  response: 'pending' | 'accepted' | 'declined' | 'ringing' | 'missed'
}

export interface MeetingParticipant {
  id: number | null
  name: string
  guest: boolean
}

export type Recurrence = '' | 'daily' | 'weekdays' | 'weekly' | 'biweekly' | 'monthly'

export interface Meeting {
  id: number
  kind: 'scheduled' | 'space' | 'call'
  title: string
  description: string
  starts_at: string | null
  ends_at: string | null
  recurrence: Recurrence
  recurrence_until: string | null
  next_start: string | null
  next_end: string | null
  space_id: number | null
  space_name: string | null
  organizer: UserBrief | null
  invitees: MeetingPerson[]
  my_response: MeetingPerson['response'] | null
  is_organizer: boolean
  guest_link: string | null
  live: MeetingParticipant[]
  cancelled: boolean
  town_hall?: boolean
  e2ee?: boolean
  e2ee_forced?: boolean
  is_moderator?: boolean
}

export interface MeetingDetail extends Meeting {
  notes: string
  notes_version: number
  waiting: { id: number; name: string; since: string }[]
}

export interface IncomingCall {
  meeting_id: number
  caller: UserBrief | null
  title: string
  started: string
}

export interface CalendarEntry {
  id: string
  kind: 'meeting' | 'booking' | 'vacation' | 'home_office' | 'holiday' | 'event'
  title: string
  start: string | null
  end: string | null
  day: string | null
  last_day: string | null
  detail: string
  status: string
  link: string
  series?: boolean
}

export type PresenceState = 'available' | 'busy' | 'in_meeting' | 'dnd' | 'away' | 'ooo' | 'offline'
export type ManualPresence = 'auto' | 'available' | 'busy' | 'dnd' | 'away' | 'offline'

export interface Presence {
  state: PresenceState
  text: string
  manual: ManualPresence
  activity?: { kind: 'editing' | 'meeting'; label: string; link: string } | null
}
