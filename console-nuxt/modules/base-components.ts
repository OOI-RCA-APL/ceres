import { addComponent, defineNuxtModule } from 'nuxt/kit'

// The C-prefixed inventory of Nuxt UI components the console uses, registered
// globally so templates write <c-button> with no import. Application code never
// names a U* component. Wrapping a primitive later means removing its row here and
// adding the wrapper to app/components/base/, where it auto-registers under the
// same name.
const nuxtUiComponents: Record<string, string> = {
  CApp: 'App',
  CBadge: 'Badge',
  CButton: 'Button',
  CCard: 'Card',
  CCheckbox: 'Checkbox',
  CForm: 'Form',
  CFormField: 'FormField',
  CIcon: 'Icon',
  CInput: 'Input',
  CMenu: 'DropdownMenu',
  CModal: 'Modal',
  CPopover: 'Popover',
  CSelect: 'Select',
  CSelectMenu: 'SelectMenu',
  CSwitch: 'Switch',
  CTable: 'Table',
  CTabs: 'Tabs',
  CTooltip: 'Tooltip',
}

export default defineNuxtModule({
  meta: {
    name: 'base-components',
  },
  setup() {
    for (const [name, source] of Object.entries(nuxtUiComponents)) {
      addComponent({
        name,
        filePath: `@nuxt/ui/components/${source}.vue`,
      })
    }
  },
})
