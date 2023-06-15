<script lang="ts" setup>
import { Address } from '@/address'
import { ComponentConfig, Config } from '@/api/models'
import AlertsIndicator from '@/components/AlertsIndicator.vue'
import { useDrawer } from '@/drawer'
import icons from '@/icons'
import { useRouter } from 'vue-router'

const { address, config } = defineProps<{
  address: Address
  config: Config | ComponentConfig
}>()

const router = useRouter()
const drawer = useDrawer()
const isExpanded = $computed(
  () => !drawer.collapsedComponents.some((current) => current.equals(address))
)
const isLeaf = $computed(() => config.components.length === 0)

function toggleExpanded() {
  if (isExpanded) {
    drawer.collapsedComponents = [...drawer.collapsedComponents, address]
  } else {
    drawer.collapsedComponents = drawer.collapsedComponents.filter(
      (current) => !current.equals(address)
    )
  }
}

console.log(address, address.depth)
</script>

<template>
  <q-item
    :class="[$style.root, 'items-center', 'row']"
    clickable
    dense
    :to="`/components/${address}`"
  >
    <div
      :class="[$style.iconContainer, 'items-center', 'justify-center', 'row']"
      :style="{ marginLeft: `${8 * address.depth}px` }"
    >
      <q-btn
        class="q-mr-sm"
        flat
        round
        size="xs"
        :tabindex="isLeaf ? -1 : 0"
        :to="isLeaf ? `/components/${address}` : undefined"
        @click.stop.prevent="isLeaf ? router.push(`/components/${address}`) : toggleExpanded()"
      >
        <q-icon v-if="isLeaf" :name="icons.circle" size="6px" />
        <q-icon v-else :name="isExpanded ? icons.arrowDown : icons.arrowRight" size="20px" />
      </q-btn>
    </div>
    <q-item-section no-wrap>
      <q-item-label class="q-ml-md text-no-wrap">{{ config.name || '@' }}</q-item-label>
    </q-item-section>
    <q-item-section side>
      <alerts-indicator :address="address" />
    </q-item-section>
  </q-item>
  <div v-if="!isLeaf && isExpanded">
    <app-layout-drawer-component
      v-for="child in config.components"
      :key="child.name"
      :address="address.append(child.name)"
      :config="child"
    />
  </div>
</template>

<style module>
.root {
  min-height: 38px;
}

.iconContainer {
  min-width: 40px;
}
</style>
