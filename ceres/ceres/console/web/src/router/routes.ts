import AppLayout from '@/AppLayout.vue'
import Connection from '@/pages/Connection.vue'
import Unit from '@/pages/Unit.vue'
import Units from '@/pages/Units.vue'
import { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '',
    component: AppLayout,
    children: [
      {
        path: '',
        redirect: '/units',
      },
      {
        path: '/units',
        component: Units,
        children: [
          {
            path: ':unitName/connections/:connectionName',
            component: Connection,
            props: (route) => ({
              unitName: route.params.unitName,
              connectionName: route.params.connectionName,
            }),
          },
          {
            path: ':name?',
            component: Unit,
            props: (route) => ({
              name: parseStringOrNull(route.params.name),
            }),
          },
        ],
      },
      // {
      //   path: '/:catchAll(.*)*',
      //   redirect: '/units',
      // },
    ],
  },
]

function parseStringOrNull(value: string | string[]) {
  if (typeof value === 'string') {
    value = value.trim()
    if (value !== '') {
      return value
    }
  }

  return value[0] ?? null
}

// function parseArray(values?: LocationQueryValue | LocationQueryValue[]) {
//   if (values == null) {
//     return []
//   }

//   if (typeof values === 'string') {
//     return values
//       .split(',')
//       .map((value) => value.trim())
//       .filter((value) => value !== '')
//   }

//   return values
// }

export default routes
