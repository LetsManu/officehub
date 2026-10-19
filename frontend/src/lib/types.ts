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
}

export interface UserBrief {
  id: number
  full_name: string
  department: string
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
  manager_name: string | null
  total: number
  done: number
  tasks: OnboardingTask[]
}

export interface ChecklistSummary {
  person: UserBrief
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
