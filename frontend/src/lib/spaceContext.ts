/** The space a page inside /spaces/:id belongs to, shared by the space layout with its tabs. */

import { inject, provide, type Ref } from 'vue'
import type { SpaceDetail } from './types'

interface SpaceContext {
  space: Ref<SpaceDetail | null>
  reload: () => Promise<void>
}

const KEY = Symbol('space')

export function provideSpace(context: SpaceContext): void {
  provide(KEY, context)
}

export function useSpace(): SpaceContext {
  const context = inject<SpaceContext>(KEY)
  if (!context) throw new Error('useSpace() outside a space page')
  return context
}
