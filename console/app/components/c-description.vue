<script lang="ts" setup>
import { useResizeObserver } from '@vueuse/core'
import { nextTick, onMounted, useTemplateRef, watch } from 'vue'

import icons from '@/icons'
import { renderMarkdown } from '@/markdown'
import { lineBottoms } from '@/text-lines'

const { text, lines = 3 } = defineProps<{
  /** Markdown, a docstring or a field's description. */
  text: string
  /** How many lines show while folded. */
  lines?: number
}>()

const html = $computed(() => renderMarkdown(text))

let isExpanded = $ref(false)
// Where the folded text is cut, the bottom of its last shown line, and how many lines lie below.
let foldAt = $ref<number | null>(null)
let hiddenLines = $ref(0)

const content = useTemplateRef<HTMLElement>('content')

function measure() {
  const element = content.value
  if (element == null) {
    return
  }

  // A single line past the fold takes no more room than the toggle that would hide it.
  const bottoms = lineBottoms(element)
  hiddenLines = bottoms.length - lines
  foldAt = hiddenLines > 1 ? bottoms[lines - 1]! : null
}

useResizeObserver(content, measure)
watch(
  () => html,
  () => nextTick(measure),
)
onMounted(measure)

const isFolded = $computed(() => foldAt != null && !isExpanded)
</script>

<!-- Markdown text folded to its first few lines, with a toggle to unfold the rest when there is more
than fits. -->
<template>
  <div>
    <!-- Rendered with raw HTML off, so the text cannot inject markup. -->
    <!-- eslint-disable vue/no-v-html -->
    <div
      ref="content"
      class="c-description"
      :class="isFolded && 'c-description-folded'"
      :style="isFolded ? { maxHeight: `${foldAt}px` } : undefined"
      v-html="html"
    />
    <!-- eslint-enable vue/no-v-html -->
    <button
      v-if="foldAt != null"
      class="text-muted hover:text-default mt-0.5 flex cursor-pointer items-center gap-0.5 text-[11px]"
      type="button"
      @click="isExpanded = !isExpanded"
    >
      <c-icon :name="isExpanded ? icons.chevronUp : icons.chevronDown" size="14" />
      {{ isExpanded ? 'Fold' : `${hiddenLines} more ${hiddenLines === 1 ? 'line' : 'lines'}` }}
    </button>
  </div>
</template>

<style scoped>
.c-description-folded {
  overflow: hidden;
}

.c-description :deep(p),
.c-description :deep(ul),
.c-description :deep(ol),
.c-description :deep(pre),
.c-description :deep(blockquote) {
  margin: 0 0 0.5em;
}

.c-description :deep(> :last-child) {
  margin-bottom: 0;
}

.c-description :deep(ul) {
  list-style: disc;
  padding-left: 1.25em;
}

.c-description :deep(ol) {
  list-style: decimal;
  padding-left: 1.25em;
}

.c-description :deep(code) {
  font-family: var(--font-mono);
  font-size: 0.95em;
  border-radius: 0.25rem;
  background: var(--ui-bg-elevated);
  padding: 0 0.25em;
}

.c-description :deep(pre) {
  overflow-x: auto;
  border-radius: 0.25rem;
  background: var(--ui-bg-elevated);
  padding: 0.5em;
}

.c-description :deep(pre code) {
  background: none;
  padding: 0;
}

.c-description :deep(a) {
  color: var(--ui-primary);
  text-decoration: underline;
}

.c-description :deep(strong) {
  font-weight: 600;
}

.c-description :deep(blockquote) {
  border-left: 2px solid var(--ui-border);
  padding-left: 0.5em;
}

.c-description :deep(h1),
.c-description :deep(h2),
.c-description :deep(h3),
.c-description :deep(h4) {
  font-weight: 500;
  margin: 0 0 0.25em;
}
</style>
