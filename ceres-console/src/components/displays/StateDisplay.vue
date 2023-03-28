<script lang="ts" setup>
import CommonText from '@/components/CommonText.vue'
import { StateDisplayInfo } from '@/display'

const { info } = defineProps<{
  info: StateDisplayInfo
}>()

const selected = $computed(() => info.options.find((state) => state.value === info.value ?? null))
</script>

<template>
  <q-chip
    class="cursor-pointer q-px-sm"
    dense
    :icon="selected?.icon ?? undefined"
    :style="{
      backgroundColor: selected?.color ?? 'transparent',
    }"
  >
    <common-text :style="{ color: 'white', fontWeight: 300 }" variant="body1">
      {{ selected?.label ?? '?' }}
    </common-text>
    <q-menu
      anchor="bottom middle"
      no-refocus
      :offset="[0, 8]"
      self="top middle"
      transition-duration="100"
      transition-hide="scale"
      transition-show="scale"
      @click.stop.prevent
    >
      <div>
        <q-card bordered flat>
          <div class="items-center q-px-sm q-py-sm row text-capitalize">
            <span class="text-faded">Possible States</span>
            <q-space />
          </div>
          <q-markup-table bordered class="self-options-table" dense flat separator="cell">
            <tbody>
              <q-tr
                v-for="option in info.options"
                :key="String(option.value) + typeof option.value"
              >
                <q-th class="text-capitalize text-right">
                  <q-chip
                    class="q-px-sm self-option-chip"
                    dense
                    :icon="option.icon ?? undefined"
                    :style="{
                      backgroundColor: option.color ?? 'transparent',
                    }"
                  >
                    <common-text :style="{ color: 'white', fontWeight: 300 }" variant="body1">
                      {{ option.label }}
                    </common-text>
                  </q-chip>
                </q-th>
                <q-td class="text-left" no-hover>
                  {{ option.description ?? 'No description available.' }}
                </q-td>
              </q-tr>
            </tbody>
          </q-markup-table>
        </q-card>
      </div>
    </q-menu>
  </q-chip>
</template>

<style lang="scss" scoped>
.self-options-table th {
  padding-left: 8px !important;
}

.self-option-chip {
  scale: 0.85;
}
</style>
