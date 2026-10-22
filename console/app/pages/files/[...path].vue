<script lang="ts" setup>
import type { BreadcrumbItem } from '@nuxt/ui'
import { useRoute, useRouter } from 'vue-router'

import { useQuery } from '@/api/client'
import { useEngine } from '@/api/engine'
import { type FileMount, filesPagePath } from '@/api/files'
import icons from '@/icons'

definePageMeta({ auth: true })

const engine = useEngine()
const router = useRouter()

// Read once, since a page instance belongs to one path (see `usePageParameter`). The first
// segment names the mount, the rest is the path under it.
const segments = (() => {
  const value = useRoute().params.path
  return Array.isArray(value) ? [...value] : value != null && value !== '' ? [value] : []
})()
const mount = segments[0] ?? null
const path = segments.slice(1)

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
