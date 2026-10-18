import { reactive } from 'vue'

export type ToastKind = 'success' | 'info' | 'error'

export interface Toast {
  id: number
  kind: ToastKind
  message: string
}

const DURATION_MS = 5000
let nextId = 1

export const toasts = reactive<Toast[]>([])

export function dismissToast(id: number): void {
  const index = toasts.findIndex((t) => t.id === id)
  if (index >= 0) toasts.splice(index, 1)
}

export function showToast(message: string, kind: ToastKind = 'success'): void {
  const id = nextId++
  toasts.push({ id, kind, message })
  if (toasts.length > 3) toasts.shift()
  // Errors stay a little longer so they can be read.
  window.setTimeout(() => dismissToast(id), kind === 'error' ? DURATION_MS + 1000 : DURATION_MS)
}
