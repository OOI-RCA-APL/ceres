<script lang="ts">
export type TextVariant =
  | 'title1'
  | 'title2'
  | 'title3'
  | 'body1'
  | 'body2'
  | 'body3'
  | 'th'
  | 'description'
  | 'value'
  | 'mono-lg'
  | 'mono-md'
  | 'mono-sm'
  | 'mono-xs'

export const variantClasses: Record<TextVariant, string> = {
  // A two point step between them, close enough that a heading reads as one rank above the body
  // text under it rather than as a banner over it.
  title1: 'text-[19px] font-light leading-normal',
  title2: 'text-[15px] font-light leading-normal',
  title3: 'text-[13px] font-light leading-normal',
  body1: 'text-base font-normal leading-6 tracking-[0.03125em]',
  body2: 'text-sm font-normal leading-6 tracking-[0.03125em]',
  body3: 'text-xs font-normal leading-5 tracking-[0.03125em]',
  th: 'text-xs font-medium',
  description: 'text-[11px] text-muted',
  value: 'text-lg font-light leading-normal',
  'mono-lg': 'font-mono text-[13px] font-normal whitespace-pre',
  'mono-md': 'font-mono text-xs font-normal whitespace-pre',
  'mono-sm': 'font-mono text-[11px] font-normal whitespace-pre',
  'mono-xs': 'font-mono text-[10px] font-normal whitespace-pre',
}
</script>

<script lang="ts" setup>
const { element, inline = false } = defineProps<{
  variant: TextVariant
  /** Flows with the text around it, for a phrase set inside a sentence. Applies to a named
  `element` as well, so a heading can be laid out beside other text. */
  inline?: boolean
  /** The tag to render, for a heading or preformatted text. */
  element?: string
}>()

// Block otherwise, because the vertical spacing utilities and `truncate` that most call sites
// carry have no effect on an inline box.
const tag = $computed(() => element ?? (inline ? 'span' : 'div'))
</script>

<template>
  <component :is="tag" :class="[variantClasses[variant], inline && 'inline']">
    <slot />
  </component>
</template>
