<template>
  <q-btn-toggle
    v-if="info.show_options"
    v-model="info.value"
    class="no-pointer-events"
    color="grey-5"
    :options="options as any"
    readonly
    :ripple="false"
    size="md"
    :stack="info.vertical_icons"
    text-color="grey-4"
    :toggle-color="selected?.color"
  />
  <q-chip
    v-else
    :icon="selected?.icon ?? undefined"
    :label="selected?.label"
    :ripple="false"
    square
    :stack="info.vertical_icons"
    :style="{ backgroundColor: selected?.color ?? 'transparent' }"
    text-color="white"
  >
    <q-menu
      anchor="bottom middle"
      no-refocus
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
          <q-markup-table
            bordered
            class="activity-status-indicator-table"
            dense
            flat
            separator="cell"
          >
            <tbody>
              <q-tr
                v-for="option in info.options"
                v-bind:key="String(option.value) + typeof option.value"
              >
                <q-th class="text-capitalize text-center">
                  <q-chip
                    :color="option.color ?? 'primary'"
                    :icon="option.icon ?? undefined"
                    :label="option.label"
                    :ripple="false"
                    size="sm"
                    square
                    text-color="white"
                  />
                </q-th>
                <q-td class="text-left">
                  {{ option.description ? option.description : 'No description available.' }}
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
import { StateDisplayInfo } from '@/display'

const { info } = defineProps<{
  info: StateDisplayInfo
}>()

const selected = $computed(() => info.options.find((state) => state.value === info.value))
const options = $computed(() =>
  info.options.map((state) => ({
    label: state.value as string,
    value: state.value,
    icon: state.icon,
  }))
)
</script>

<style lang="scss" scoped>
.self-state-box {
  box-shadow: inset 0px 0px 2px black;
}
</style>

<style lang="scss">
.activity-status-indicator-table th {
  padding-left: 8px !important ;
}
</style>
