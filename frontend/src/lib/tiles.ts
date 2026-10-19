/** Dashboard tiles HR can choose from (keys must match TILE_KEYS in the backend). */

export interface TileDefinition {
  key: string
  to: string
  icon: string
  label: string // translation key
}

export const TILES: TileDefinition[] = [
  { key: 'vacation', to: '/requests/new/vacation', icon: 'sun', label: 'dashboard.requestVacation' },
  { key: 'expense', to: '/requests/new/expense', icon: 'receipt', label: 'dashboard.submitExpense' },
  { key: 'equipment', to: '/requests/new/equipment', icon: 'laptop', label: 'dashboard.requestEquipment' },
  { key: 'home_office', to: '/requests/new/home_office', icon: 'home', label: 'tiles.homeOffice' },
  { key: 'it_access', to: '/requests/new/it_access', icon: 'key', label: 'tiles.itAccess' },
  { key: 'appointment', to: '/requests/new/appointment', icon: 'calendar', label: 'tiles.appointment' },
  { key: 'documents', to: '/documents', icon: 'search', label: 'dashboard.findDocuments' },
  { key: 'directory', to: '/people', icon: 'users', label: 'tiles.directory' },
  { key: 'phone_list', to: '/people?view=phones', icon: 'phone', label: 'tiles.phoneList' },
  { key: 'rooms', to: '/rooms', icon: 'door', label: 'tiles.rooms' },
  { key: 'visitors', to: '/visitors', icon: 'badge', label: 'tiles.visitors' },
]

export const DEFAULT_TILES = ['vacation', 'expense', 'equipment', 'documents']

export function tileByKey(key: string): TileDefinition | undefined {
  return TILES.find((tile) => tile.key === key)
}
