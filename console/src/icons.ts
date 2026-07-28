import { mdiPlus } from '@quasar/extras/mdi-v7'

const icons = {
  // The webfont mdi-plus glyph can rasterize slightly off-center in small round buttons at some
  // zoom levels, the SVG version centers geometrically.
  add: mdiPlus,
  admin: 'admin_panel_settings', // Material Icons
  all: 'mdi-asterisk',
  arrowDown: 'mdi-arrow-down',
  arrowLeft: 'mdi-arrow-left',
  arrowUp: 'mdi-arrow-up',
  cancel: 'mdi-close-circle',
  clear: 'mdi-close-circle',
  changeRole: 'mdi-account-convert',
  chevronLeft: 'mdi-chevron-left',
  chevronRight: 'mdi-chevron-right',
  circle: 'mdi-circle',
  clearLocalStorage: 'mdi-delete-sweep',
  close: 'mdi-close',
  configuration: 'mdi-cogs',
  confirm: 'mdi-check',
  connection: 'route', // Material Icons
  copy: 'mdi-content-copy',
  darkMode: 'dark_mode',
  delete: 'mdi-delete',
  developer: 'construction', // Material Icons
  disable: 'mdi-minus-circle-outline',
  discard: 'mdi-arrow-u-left-top',
  drawer: 'mdi-menu',
  group: 'mdi-account-group',
  duplicate: 'mdi-content-duplicate',
  edit: 'mdi-pencil',
  editor: 'mdi-account-edit',
  enable: 'mdi-check-circle-outline',
  export: 'mdi-download',
  filter: 'mdi-filter',
  grab: 'mdi-grab',
  help: 'mdi-help',
  home: 'mdi-home',
  import: 'mdi-upload',
  join: 'mdi-star-outline',
  joined: 'mdi-star',
  json: 'mdi-code-json',
  leave: 'mdi-exit-run',
  lightMode: 'light_mode', // Material Icons
  locked: 'mdi-lock-outline',
  logout: 'mdi-logout', // Material Icons
  manage: 'mdi-cog',
  manager: 'mdi-account-star',
  menuDown: 'mdi-menu-down',
  menuLeft: 'mdi-menu-left',
  menuRight: 'mdi-menu-right',
  menuUp: 'mdi-menu-up',
  more: 'mdi-dots-horizontal',
  moreVertical: 'mdi-dots-vertical',
  open: 'mdi-open-in-new',
  operate: 'mdi-wrench',
  operations: 'mdi-cog-transfer',
  overview: 'space_dashboard', // Material Icons
  password: 'password', // Material Icons
  preferences: 'mdi-theme-light-dark',
  reload: 'mdi-cog-sync',
  refresh: 'mdi-refresh',
  removeMember: 'mdi-account-remove',
  rename: 'mdi-rename',
  revertToOriginal: 'mdi-restore',
  search: 'mdi-magnify',
  send: 'mdi-send',
  settings: 'mdi-cog',
  start: 'mdi-play',
  stop: 'mdi-stop',
  submit: 'mdi-check',
  switchLeft: 'switch_left', // Material Icons
  switchRight: 'switch_right', // Material Icons
  user: 'mdi-account',
  view: 'mdi-eye',
  viewOriginal: 'mdi-eye-arrow-left',
  viewer: 'mdi-account-eye',
  privateWorkspace: 'mdi-account',
  workingCopy: 'mdi-pencil-box-multiple',
  workspace: 'mdi-dots-grid',
} as const

export default icons
