export type Role = 'employee' | 'manager' | 'admin'
export type Language = 'de' | 'en'

export type RequestType = 'vacation' | 'home_office' | 'equipment' | 'expense' | 'it_access' | 'general'
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
  demo_mode: boolean
  max_upload_mb: number
  demo_accounts?: DemoAccount[]
  demo_password?: string
}
