<script lang="ts" setup>
import { useResizeObserver } from '@vueuse/core'
import { nextTick, onMounted, useTemplateRef, watch } from 'vue'

import { renderMarkdown } from '@/markdown'

const { text, lines = 3 } = defineProps<{
  /** Markdown, a docstring or a field's description. */
  text: string
  /** How many lines show while collapsed. */
  lines?: number
}>()

const html = $computed(() => renderMarkdown(text))

let isExpanded = $ref(false)
// Whether the collapsed text runs past its lines, the only case worth a "Show more".
let isOverflowing = $ref(false)

const content = useTemplateRef<HTMLElement>('content')

function measure() {
  const element = content.value
  // Expanded, nothing is cut, so the last collapsed measure stands.
  if (element == null || isExpanded) {
    return
  }
  isOverflowing = element.scrollHeight > element.clientHeight + 1
}

useResizeObserver(content, measure)
watch(
  () => html,
  () => nextTick(measure),
)
onMounted(measure)
</script>

<!-- Markdown text cut to a few lines with an ellipsis, and a link to show the rest when there is
more than fits. -->
<template>
  <div>
    <!-- Rendered with raw HTML off, so the text cannot inject markup. -->
    <!-- eslint-disable vue/no-v-html -->
    <div
      ref="content"
      class="c-description"
      :class="!isExpanded && 'c-description-clamped'"
      :style="!isExpanded ? { WebkitLineClamp: lines } : undefined"
      v-html="html"
    />
    <!-- eslint-enable vue/no-v-html -->
    <button
      v-if="isOverflowing"
      class="text-primary mt-0.5 cursor-pointer text-[11px] hover:underline"
      type="button"
      @click="isExpanded = !isExpanded"
    >
      {{ isExpanded ? 'Show less' : 'Show more' }}
    </button>
  </div>
</template>

<style scoped>
.c-description-clamped {
  display: -webkit-box;
  -webkit-box-orient: vertical;
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
