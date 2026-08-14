<script lang="ts" setup>
import {
  CBadge,
  CButton,
  CCard,
  CCheckbox,
  CInput,
  CSelect,
  CSwitch,
  CTooltip,
} from '@/components/base'

const semanticColors = ['primary', 'success', 'warning', 'error', 'info', 'neutral'] as const

let inputValue = $ref('')
let selectValue = $ref('alpha')
let checked = $ref(true)
let switched = $ref(false)

const selectItems = ['alpha', 'beta', 'gamma']
</script>

<template>
  <div class="flex flex-col gap-8 p-8">
    <h1 class="text-[22px] font-light leading-normal">Base Components</h1>

    <section class="flex flex-col gap-3">
      <h2 class="text-lg font-light leading-normal">Buttons</h2>
      <div class="flex flex-wrap items-center gap-3">
        <c-button v-for="color in semanticColors" :key="color" :color="color">
          {{ color }}
        </c-button>
        <c-button color="neutral" variant="outline">outline</c-button>
        <c-button color="neutral" variant="ghost">ghost</c-button>
        <c-button disabled>disabled</c-button>
      </div>
    </section>

    <section class="flex flex-col gap-3">
      <h2 class="text-lg font-light leading-normal">Badges</h2>
      <div class="flex flex-wrap items-center gap-3">
        <c-badge v-for="color in semanticColors" :key="color" :color="color">
          {{ color }}
        </c-badge>
      </div>
    </section>

    <section class="flex max-w-md flex-col gap-3">
      <h2 class="text-lg font-light leading-normal">Inputs</h2>
      <c-input v-model="inputValue" placeholder="Type something" />
      <c-select v-model="selectValue" :items="selectItems" />
      <c-checkbox v-model="checked" label="Checkbox" />
      <c-switch v-model="switched" label="Switch" />
    </section>

    <section class="flex max-w-md flex-col gap-3">
      <h2 class="text-lg font-light leading-normal">Overlays</h2>
      <div class="flex items-center gap-3">
        <c-tooltip text="A tooltip">
          <c-button color="neutral" variant="outline">hover me</c-button>
        </c-tooltip>
      </div>
    </section>

    <section class="flex max-w-md flex-col gap-3">
      <h2 class="text-lg font-light leading-normal">Cards</h2>
      <c-card>
        <template #header>Card header</template>
        Card body content.
      </c-card>
    </section>
  </div>
</template>
