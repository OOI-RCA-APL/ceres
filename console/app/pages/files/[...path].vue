<script lang="ts" setup>
import type { BreadcrumbItem } from '@nuxt/ui'
import { useRoute, useRouter } from 'vue-router'

import { useQuery } from '@/api/client'
import { useEngine } from '@/api/engine'
import { type FileRoot, filesPagePath } from '@/api/files'
import icons from '@/icons'

definePageMeta({ auth: true })

const engine = useEngine()
const router = useRouter()

// Read once, since a page instance belongs to one path (see `usePageParameter`). The first
// segment names the root, the rest is the path under it.
const segments = (() => {
  const value = useRoute().params.path
  return Array.isArray(value) ? [...value] : value != null && value !== '' ? [value] : []
})()
const root = segments[0] ?? null
const path = segments.slice(1)

const rootsQuery = useQuery({
  queryKey: ['files', 'roots'],
  queryFn: () => engine.files.getRoots(),
})
const roots = $computed<FileRoot[]>(() => rootsQuery.data.value ?? [])

const home: BreadcrumbItem[] = [{ label: 'Files', icon: icons.files, to: filesPagePath(null) }]

function linkTo(target: string[]) {
  return filesPagePath(root, target)
}

// A move or delete changes the path in place, which on this page means going to the new one.
async function open(target: string[]) {
  await router.push(linkTo(target))
}
</script>

<template>
  <c-full-page fill title="Files">
    <div class="flex min-h-full flex-col gap-3 p-4">
      <c-file-browser
        v-if="root != null"
        class="flex-1"
        :home
        :link-to
        :path
        :root
        @update:path="open"
      />

      <!-- The root picker. -->
      <template v-else>
        <c-breadcrumb :items="home" />
        <c-text
          v-if="rootsQuery.isSuccess.value && roots.length === 0"
          class="text-muted"
          variant="body2"
        >
          No file roots are available to you.
        </c-text>
        <c-list>
          <c-list-item v-for="current in roots" :key="current.id" :to="filesPagePath(current.id)">
            <c-icon class="shrink-0" :name="icons.directory" size="16" />
            <c-text class="min-w-0 flex-1 truncate" variant="body2">{{ current.label }}</c-text>
            <c-text class="text-muted min-w-0 truncate" variant="body2">
              {{ current.component ?? 'Project' }}
            </c-text>
          </c-list-item>
        </c-list>
      </template>
    </div>
  </c-full-page>
</template>
