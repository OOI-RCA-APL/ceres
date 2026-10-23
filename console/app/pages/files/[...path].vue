<script lang="ts" setup>
import type { BreadcrumbItem } from '@nuxt/ui'
import { watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useQuery } from '@/api/client'
import { useEngine } from '@/api/engine'
import {
  type FileMount,
  filesPageKey,
  filesPagePath,
  filesRouteSegments,
  parseFilesRoute,
} from '@/api/files'
import icons from '@/icons'

// One instance per mount, so a step to another file in it keeps the listing in place.
definePageMeta({ auth: true, key: (route) => filesPageKey(route.params.path) })

const engine = useEngine()
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

const mountsQuery = useQuery({
  queryKey: ['files', 'mounts'],
  queryFn: () => engine.files.getMounts(),
})
const mounts = $computed<FileMount[]>(() => mountsQuery.data.value ?? [])

const home: BreadcrumbItem[] = [{ label: 'Files', icon: icons.files, to: filesPagePath(null) }]

function linkTo(target: string[]) {
  return filesPagePath(mount, target)
}

// A move or delete changes the path in place, which on this page means going to the new one.
async function open(target: string[]) {
  await router.push(linkTo(target))
}

// A step through files by selection replaces the URL, so going back leaves the directory.
async function preview(target: string[]) {
  if (route.path !== linkTo(target)) {
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
        :home
        :link-to
        :mount
        :path
        @preview="preview"
        @update:path="open"
      />

      <!-- The mount picker. -->
      <template v-else>
        <c-breadcrumb :items="home" />
        <c-text
          v-if="mountsQuery.isSuccess.value && mounts.length === 0"
          class="text-muted"
          variant="body2"
        >
          No folders are available to you.
        </c-text>
        <c-list>
          <c-file-mount
            v-for="current in mounts"
            :key="current.id"
            :mount="current"
            show-component
          />
        </c-list>
      </template>
    </div>
  </c-full-page>
</template>
