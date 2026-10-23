<script lang="ts" setup>
import { computed, watch } from 'vue'

import { useQuery } from '@/api/client'
import { useEngine } from '@/api/engine'
import {
  type FileEntry,
  HIGHLIGHT_LIMIT,
  fileKindLabels,
  filesDownloadPath,
  formatFileSize,
  formatFileTime,
  highlightLanguageOf,
  previewOf,
} from '@/api/files'
import icons from '@/icons'
import { type HighlightLanguage, highlight, loadHighlightLanguage } from '@/utilities'

const {
  mount,
  path,
  entry,
  hidden = false,
  bare = false,
} = defineProps<{
  /** The ID of the mount `path` is under. */
  mount: string
  /** Where `entry` is under the mount. */
  path: string[]
  entry: FileEntry
  /** Whether a folder's download keeps dot names, as the listing beside it shows them. */
  hidden?: boolean
  /** Leave out the header, for a preview whose page already names the entry and offers its
  actions. */
  bare?: boolean
}>()

const emit = defineEmits<{
  /** Open the entry, a directory's only action here. */
  open: []
  info: []
}>()

const engine = useEngine()

const preview = $computed(() => previewOf(entry))
const sourceUrl = $computed(() => engine.files.sourceUrl(mount, path))
const downloadUrl = $computed(() => filesDownloadPath(mount, path, { hidden }))

const textQuery = useQuery({
  queryKey: computed(() => ['files', 'text', mount, ...path]),
  queryFn: () => engine.files.readText(mount, path, entry.size ?? 0),
  enabled: computed(() => preview === 'text'),
})
const text = $computed(() => textQuery.data.value)

const language = $computed<HighlightLanguage | null>(() =>
  entry.size != null && entry.size <= HIGHLIGHT_LIMIT ? highlightLanguageOf(entry.name) : null,
)

// The text shows plain until its grammar loads, so a slow import never holds it back.
let loadedLanguage = $ref<HighlightLanguage | null>(null)
watch(
  // The cast drops the reactivity transform's brand, which an assignment to a `$ref` refuses.
  () => language as HighlightLanguage | null,
  (next) => {
    if (next != null) {
      // A slower import finishing after a step to another file must not claim that file.
      void loadHighlightLanguage(next).finally(() => {
        if ((language as HighlightLanguage | null) === next) {
          loadedLanguage = next
        }
      })
    }
  },
  { immediate: true },
)

// A grammar that failed to load or rejects the text leaves the text plain.
const highlighted = $computed(() => {
  if (text == null || language == null || loadedLanguage !== language) {
    return null
  }

  try {
    return highlight(text, language)
  } catch {
    return null
  }
})
</script>

<template>
  <div class="flex min-h-0 flex-col gap-3">
    <div v-if="!bare" class="flex shrink-0 items-center gap-2">
      <c-icon
        class="shrink-0"
        :name="entry.kind === 'directory' ? icons.folder : icons.file"
        size="16"
      />
      <c-text class="min-w-0 flex-1 truncate" variant="body2">{{ entry.name }}</c-text>
      <template v-if="entry.kind === 'file'">
        <c-tooltip text="View Raw">
          <c-button
            aria-label="View Raw"
            color="neutral"
            external
            :href="sourceUrl"
            :icon="icons.open"
            size="xs"
            target="_blank"
            variant="ghost"
          />
        </c-tooltip>
        <c-tooltip text="Download">
          <c-button
            aria-label="Download"
            color="neutral"
            external
            :href="downloadUrl"
            :icon="icons.download"
            size="xs"
            variant="ghost"
          />
        </c-tooltip>
      </template>
      <c-tooltip text="Info">
        <c-button
          aria-label="Info"
          color="neutral"
          :icon="icons.details"
          size="xs"
          variant="ghost"
          @click="emit('info')"
        />
      </c-tooltip>
    </div>

    <div class="flex min-h-0 flex-1 flex-col gap-3 overflow-auto">
      <div
        v-if="entry.kind !== 'file'"
        class="flex flex-1 flex-col items-center justify-center gap-2 py-8 text-center"
      >
        <c-icon
          class="text-dimmed"
          :name="entry.kind === 'directory' ? icons.folder : icons.fileOther"
          size="64"
        />
        <c-text variant="title2">{{ entry.name }}</c-text>
        <c-text class="text-muted" variant="body2">
          {{ fileKindLabels[entry.kind] }}
          <template v-if="entry.kind === 'other' && entry.size != null">
            &middot; {{ formatFileSize(entry.size) }}
          </template>
        </c-text>
        <c-button
          v-if="entry.kind === 'directory'"
          color="neutral"
          :icon="icons.chevronRight"
          label="Open"
          size="sm"
          variant="outline"
          @click="emit('open')"
        />
        <c-button
          v-else
          color="neutral"
          external
          :href="downloadUrl"
          :icon="icons.download"
          label="Download"
          size="sm"
          variant="outline"
        />
      </div>

      <template v-else>
        <c-text v-if="!bare" class="text-muted shrink-0" variant="body2">
          {{ formatFileSize(entry.size) }} &middot; {{ formatFileTime(entry.modified) }}
        </c-text>
        <img
          v-if="preview === 'image'"
          :alt="entry.name"
          class="max-w-full self-start"
          :src="sourceUrl"
        />
        <video
          v-else-if="preview === 'video'"
          class="max-w-full self-start"
          controls
          :src="sourceUrl"
        />
        <audio
          v-else-if="preview === 'audio'"
          class="w-full max-w-[640px]"
          controls
          :src="sourceUrl"
        />
        <template v-else-if="preview === 'text'">
          <div v-if="text === null" class="flex flex-col items-start gap-2">
            <c-text class="text-muted" variant="body2">This file is binary.</c-text>
            <c-button
              color="neutral"
              external
              :href="downloadUrl"
              :icon="icons.download"
              label="Download"
              size="sm"
              variant="outline"
            />
          </div>
          <!-- eslint-disable vue/no-v-html -->
          <!-- prettier-ignore -->
          <pre
            v-else-if="highlighted != null"
            class="border-default m-0 min-h-0 overflow-auto rounded border p-3 text-xs"
          ><code v-html="highlighted" /></pre>
          <!-- eslint-enable vue/no-v-html -->
          <pre
            v-else-if="text != null"
            class="border-default m-0 min-h-0 overflow-auto rounded border p-3 text-xs"
            >{{ text }}</pre>
        </template>
        <div v-else class="flex flex-col items-start gap-2">
          <c-text class="text-muted" variant="body2">Too large to preview.</c-text>
          <c-button
            color="neutral"
            external
            :href="downloadUrl"
            :icon="icons.download"
            label="Download"
            size="sm"
            variant="outline"
          />
        </div>
      </template>
    </div>
  </div>
</template>
