/** Sorting for tables: click a column header to sort, click again to reverse. */

import { computed, ref, type Ref } from 'vue'

export type SortValue = string | number | boolean | null | undefined

export function useSort<T>(items: Ref<T[]>, columns: Record<string, (item: T) => SortValue>, initial: string, initialDir: 'asc' | 'desc' = 'asc') {
  const key = ref(initial)
  const dir = ref<'asc' | 'desc'>(initialDir)

  const sorted = computed(() => {
    const get = columns[key.value]
    if (!get) return items.value
    const factor = dir.value === 'asc' ? 1 : -1
    return [...items.value].sort((a, b) => {
      const x = get(a)
      const y = get(b)
      if (x === y) return 0
      if (x === null || x === undefined || x === '') return 1
      if (y === null || y === undefined || y === '') return -1
      if (typeof x === 'string' && typeof y === 'string') return x.localeCompare(y, undefined, { sensitivity: 'base', numeric: true }) * factor
      return (x < y ? -1 : 1) * factor
    })
  })

  function toggle(column: string) {
    if (key.value === column) dir.value = dir.value === 'asc' ? 'desc' : 'asc'
    else {
      key.value = column
      dir.value = 'asc'
    }
  }

  function ariaSort(column: string): 'ascending' | 'descending' | 'none' {
    return key.value !== column ? 'none' : dir.value === 'asc' ? 'ascending' : 'descending'
  }

  return { sorted, key, dir, toggle, ariaSort }
}
