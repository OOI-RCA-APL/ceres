<script lang="ts" setup>
import type { BreadcrumbItem } from '@nuxt/ui'
import { isEqual } from 'lodash-es'
import { watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import {
  type FilePlace,
  filesPageKey,
  filesPagePath,
  filesRouteSegments,
  parseFilesRoute,
  useFileHistory,
} from '@/api/files'
import { FILE_BREADCRUMB_UI } from '@/components/c-file-history.vue'
import icons from '@/icons'

// One instance per mount, so a step to another file in it keeps the listing in place.
definePageMeta({ auth: true, key: (route) => filesPageKey(route.params.path) })

const route = useRoute()
const router = useRouter()

// The mount is read once, since a page instance belongs to one (see `usePageParameter`).
const initial = parseFilesRoute(filesRouteSegments(route.params.path))
const mount = initial.mount
let path = $ref(initial.path)

// A route leaving for another mount reaches this instance before it unmounts, so only a route
// within its own mount moves the path.
watch(
  () => route.params.path,
  (value) => {
    const next = parseFilesRoute(filesRouteSegments(value))
    if (next.mount === mount) {
      path = next.path
    }
  },
)

// The page's Back and Forward run across the list of mounts and every mount, so they live outside
// this instance, which belongs to one mount.
const viewKey = 'page'
const history = useFileHistory(viewKey)
watch(
  () => ({ mount, path }),
  (place) => history.record(place),
  { immediate: true },
)

async function go(place: FilePlace) {
  await router.push(filesPagePath(place.mount, place.path))
}

const home: BreadcrumbItem[] = [{ label: 'Files', icon: icons.files, to: filesPagePath(null) }]

function linkTo(target: string[]) {
  return filesPagePath(mount, target)
}

// A move or delete changes the path in place, which on this page means going to the new one.
async function open(target: string[]) {
  await router.push(linkTo(target))
}

// A step through files by selection replaces the URL, so going back leaves the directory. Compared
// by segment, since the router and `filesPagePath` encode some characters differently.
async function preview(target: string[]) {
  if (!isEqual(target, path)) {
    await router.replace(linkTo(target))
  }
}
</script>

<template>
  <c-full-page class="h-[calc(100vh-50px)]" fill title="Files">
    <!-- The page holds to the window's height, so the browser's toolbar stays in view and its
    content scrolls under it. -->
    <div class="flex min-h-0 flex-1 flex-col gap-3 overflow-auto p-4">
      <c-file-browser
        v-if="mount != null"
        class="min-h-0 flex-1"
        :history
        :home
        :link-to
        :mount
        :path
        :view-key
        @go="go"
        @preview="preview"
        @update:path="open"
      />

      <!-- The mount picker. -->
      <template v-else>
        <div class="flex items-center gap-2">
          <c-file-history :history @go="go" />
          <c-breadcrumb class="min-w-0" :items="home" :ui="FILE_BREADCRUMB_UI" />
        </div>
        <c-file-mounts />
      </template>
    </div>
  </c-full-page>
</template>
