<script lang="ts" setup>
import type { BreadcrumbItem } from '@nuxt/ui'
import { useQueryClient } from '@tanstack/vue-query'
import { computed } from 'vue'
import { useRoute } from 'vue-router'

import { useQuery } from '@/api/client'
import { useEngine } from '@/api/engine'
import {
  type FileEntry,
  type FileRoot,
  filesPagePath,
  filterEntries,
  formatFileSize,
  previewOf,
} from '@/api/files'
import { Failure } from '@/errors'
import icons from '@/icons'
import { usePersisted } from '@/persistence'
import { utc } from '@/time'

definePageMeta({ auth: true })

const engine = useEngine()
const queryClient = useQueryClient()

// Read once, since a page instance belongs to one path (see `usePageParameter`). The first
// segment names the root, the rest is the path under it.
const segments = (() => {
  const value = useRoute().params.path
  return Array.isArray(value) ? [...value] : value != null && value !== '' ? [value] : []
})()
const root = segments[0] ?? null
const path = segments.slice(1)

// One switch per root, since a root full of dot entries worth seeing says nothing about another.
const persisted = usePersisted({
  schema: ({ object, boolean }) => object({ hidden: boolean().default(false) }),
  methods: computed(() => [{ type: 'local-storage' as const, key: ['files', root ?? ''] }]),
})

let filter = $ref('')

const rootsQuery = useQuery({
  queryKey: ['files', 'roots'],
  queryFn: () => engine.files.getRoots(),
})
const roots = $computed<FileRoot[]>(() => rootsQuery.data.value ?? [])
const rootLabel = $computed(() => roots.find((current) => current.id === root)?.label ?? root)

// A root is always a directory, so only a path under one needs asking what it is.
const statQuery = useQuery({
  queryKey: ['files', 'stat', root, ...path],
  queryFn: () => engine.files.stat(root!, path),
  enabled: root != null && path.length > 0,
})
const entry = $computed<FileEntry | null>(() =>
  path.length === 0
    ? { name: '', kind: 'directory', size: null, modified: null }
    : (statQuery.data.value ?? null),
)

const listingQuery = useQuery({
  queryKey: computed(() => ['files', 'list', root, persisted.hidden, ...path]),
  queryFn: () => engine.files.list(root!, path, { hidden: persisted.hidden }),
  enabled: computed(() => root != null && entry?.kind === 'directory'),
  placeholderData: (previous) => previous,
})
const listing = $computed(() => listingQuery.data.value ?? null)
const entries = $computed(() => filterEntries(listing?.entries ?? [], filter))

const preview = $computed(() => (entry == null ? 'none' : previewOf(entry)))
const textQuery = useQuery({
  queryKey: ['files', 'text', root, ...path],
  queryFn: () => engine.files.readText(root!, path),
  enabled: computed(() => preview === 'text'),
})

const failure = $computed(() => statQuery.error.value ?? listingQuery.error.value)
const failureMessage = $computed(() => {
  if (failure instanceof Failure && failure.error.type === 'not-found-error') {
    return 'Nothing is here, or you cannot reach it.'
  }

  if (failure instanceof Failure && failure.error.type === 'not-permitted-error') {
    return 'You do not have access to this location.'
  }

  return failure == null ? null : 'The engine could not open this location.'
})

const breadcrumbs = $computed<BreadcrumbItem[]>(() => [
  { label: 'Files', icon: icons.files, to: filesPagePath(null) },
  ...(root == null ? [] : [{ label: rootLabel ?? root, to: filesPagePath(root) }]),
  ...path.map((name, index) => ({
    label: name,
    to: filesPagePath(root, path.slice(0, index + 1)),
  })),
])

function entryIcon(current: FileEntry) {
  return { directory: icons.directory, file: icons.file, other: icons.fileOther }[current.kind]
}

function formatModified(modified: string | null) {
  return modified == null ? '' : utc(modified).format('YYYY-MM-DD HH:mm:ss')
}

// Invalidating refetches only the queries this page has enabled, where `refetch` would also run
// the disabled ones, like reading a directory as text.
async function refresh() {
  await queryClient.invalidateQueries({ queryKey: ['files'] })
}
</script>

<template>
  <c-full-page fill title="Files">
    <template #header-append>
      <div class="flex-1" />
      <c-switch v-if="root != null" v-model="persisted.hidden" class="mr-3" label="Show hidden" />
      <c-tooltip text="Refresh">
        <c-button
          class="mr-2"
          color="neutral"
          :icon="icons.refresh"
          size="xs"
          variant="ghost"
          @click="refresh"
        />
      </c-tooltip>
    </template>

    <div class="flex flex-col gap-3 p-4">
      <c-breadcrumb :items="breadcrumbs" />

      <!-- The root picker. -->
      <template v-if="root == null">
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

      <c-text v-else-if="failureMessage != null" class="text-muted" variant="body2">{{
        failureMessage
      }}</c-text>

      <template v-else-if="entry?.kind === 'directory'">
        <c-input
          v-model="filter"
          class="w-full max-w-[440px]"
          :icon="icons.search"
          :loading="listingQuery.isFetching.value"
          placeholder="Filter"
          :spellcheck="false"
        >
          <template #trailing>
            <c-badge color="neutral" size="sm" variant="outline">{{ entries.length }}</c-badge>
          </template>
        </c-input>
        <c-text v-if="listing?.truncated" class="text-warning" variant="body2">
          Showing the first {{ listing.entries.length.toLocaleString() }} entries. The directory
          holds more than the engine lists at once.
        </c-text>
        <c-list>
          <c-list-item
            v-for="current in entries"
            :key="current.name"
            :to="filesPagePath(root, [...path, current.name])"
          >
            <c-icon class="shrink-0" :name="entryIcon(current)" size="16" />
            <c-text class="min-w-0 flex-1 truncate" variant="body2">{{ current.name }}</c-text>
            <c-text class="text-muted w-24 shrink-0 text-right" variant="body2">
              {{ formatFileSize(current.size) }}
            </c-text>
            <c-text class="text-muted w-44 shrink-0 text-right" variant="body2">
              {{ formatModified(current.modified) }}
            </c-text>
          </c-list-item>
        </c-list>
      </template>

      <template v-else-if="entry?.kind === 'file'">
        <div class="flex items-center gap-3">
          <c-text class="text-muted" variant="body2">
            {{ formatFileSize(entry.size) }} &middot; {{ formatModified(entry.modified) }}
          </c-text>
          <c-button
            color="neutral"
            external
            :href="engine.files.downloadUrl(root, path)"
            :icon="icons.download"
            label="Download"
            size="sm"
            variant="outline"
          />
        </div>
        <img
          v-if="preview === 'image'"
          :alt="entry.name"
          class="max-w-full self-start"
          :src="engine.files.sourceUrl(root, path)"
        />
        <video
          v-else-if="preview === 'video'"
          class="max-w-full self-start"
          controls
          :src="engine.files.sourceUrl(root, path)"
        />
        <template v-else-if="preview === 'text'">
          <c-text v-if="textQuery.data.value === null" class="text-muted" variant="body2">
            This file is binary. Download it to open it.
          </c-text>
          <pre
            v-else-if="textQuery.data.value != null"
            class="border-default overflow-auto rounded border p-3 text-sm"
            >{{ textQuery.data.value }}</pre>
        </template>
        <c-text v-else class="text-muted" variant="body2">
          This file is too large to preview. Download it to open it.
        </c-text>
      </template>

      <c-text v-else-if="entry?.kind === 'other'" class="text-muted" variant="body2">
        This entry is neither a file nor a directory, so it cannot be opened here.
      </c-text>
    </div>
  </c-full-page>
</template>
