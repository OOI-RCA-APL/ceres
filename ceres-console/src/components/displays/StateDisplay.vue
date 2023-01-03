<template>
  <q-chip
    class="cursor-pointer q-px-md q-py-xs"
    :icon="icon"
    :style="{
      backgroundColor: color,
      borderWidth: '1px',
      borderStyle: 'solid',
      borderColor: borderColor,
      borderRadius: '2px',
    }"
  >
    <common-text :style="{ color: textColor }" variant="title2">{{ label }}</common-text>
    <q-menu
      anchor="bottom middle"
      no-refocus
      :offset="[0, 8]"
      self="top middle"
      transition-duration="200"
      transition-hide="flip"
      transition-show="flip"
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
                v-bind:key="String(option.value) + typeof option.value"
              >
                <q-th class="text-capitalize text-center">
                  <q-chip
                    :icon="option.icon ?? undefined"
                    :label="option.label"
                    :ripple="false"
                    size="sm"
                    :style="{
                      backgroundColor: option.color ?? 'transparent',
                      borderWidth: '1px',
                      color: textColor,
                      borderColor: borderColor,
                      borderStyle: 'solid',
                      fontWeight: 300,
                    }"
                  />
                </q-th>
                <q-td class="text-left">
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

<script lang="ts" setup>
import CommonText from '@/components/CommonText.vue'
import { StateDisplayInfo } from '@/display'
import { useQuasar } from 'quasar'

const { info } = defineProps<{
  info: StateDisplayInfo
}>()

const quasar = useQuasar()

const selected = $computed(() => info.options.find((state) => state.value === info.value ?? null))
const icon = $computed(() => selected?.icon ?? undefined)
const color = $computed(() => selected?.color ?? undefined)
const label = $computed(() => selected?.label ?? '')
const textColor = 'white'
const borderColor = $computed(() => (quasar.dark.isActive ? 'white' : 'black'))
</script>

<style lang="scss" scoped>
.self-options-table th {
  padding-left: 8px !important;
}
</style>
