import type { RequestStatus, RequestType } from './types'

export const REQUEST_TYPES: RequestType[] = ['vacation', 'expense', 'equipment', 'home_office', 'it_access', 'general']
export const STATUSES: RequestStatus[] = ['draft', 'submitted', 'in_review', 'approved', 'rejected', 'cancelled']
export const OPEN_STATUSES: RequestStatus[] = ['submitted', 'in_review']
export const DONE_STATUSES: RequestStatus[] = ['approved', 'rejected', 'cancelled']

export const EXPENSE_CATEGORIES = ['travel', 'meals', 'office_supplies', 'training', 'software', 'other'] as const
export const EQUIPMENT_CATEGORIES = ['laptop', 'monitor', 'phone', 'furniture', 'accessories', 'parking', 'other'] as const
export const ACCESS_LEVELS = ['view', 'edit', 'admin'] as const
export const CURRENCIES = ['EUR', 'CHF', 'USD', 'GBP'] as const
export const DOCUMENT_CATEGORIES = ['handbook', 'policy', 'it', 'onboarding', 'template', 'other'] as const
export const ANNOUNCEMENT_CATEGORIES = ['general', 'event', 'it', 'hr', 'office'] as const

/** Icon name per request type (see AppIcon). */
export const TYPE_ICONS: Record<RequestType, string> = {
  vacation: 'sun',
  home_office: 'home',
  equipment: 'laptop',
  expense: 'receipt',
  it_access: 'key',
  general: 'inbox',
}
