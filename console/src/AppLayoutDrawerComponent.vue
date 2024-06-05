<script lang="ts" setup>
import AppLayoutDrawerComponent from '@/AppLayoutDrawerComponent.vue'
import { Address } from '@/api/address'
import { ComponentInfo } from '@/api/components'
import AlertsIndicator from '@/components/AlertsIndicator.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { useDrawer } from '@/drawer'
import icons from '@/icons'
import { useNavigation } from '@/navigation'

const { address, component } = defineProps<{
  address: Address
  component: ComponentInfo
}>()

const navigation = useNavigation()
const drawer = useDrawer()

const isExpanded = $computed(() => !drawer.collapsed.some((current) => current.equals(address)))
const isRoot = $computed(() => address.isRoot)
const isLeaf = $computed(() => !isRoot && component.components.length === 0)

function toggleExpanded() {
  if (isExpanded) {
    drawer.collapsed = [...drawer.collapsed, address]
  } else {
    drawer.collapsed = drawer.collapsed.filter((current) => !current.equals(address))
  }
}
</script>

<template>
  <q-item :class="[$style.root, 'items-center', 'row']" :dense="address.depth > 0">
    <div
      :class="[$style.iconContainer, 'items-center', 'justify-center', 'row']"
      :style="{ marginLeft: `${8 * address.depth}px` }"
    >
      <q-btn
        :class="$style.toggleButton"
        flat
        round
        size="xs"
        :tabindex="isLeaf ? -1 : 0"
        :to="isLeaf ? `/components/${address}` : undefined"
        @click.stop.prevent="isLeaf ? navigation.go(`/components/${address}`) : toggleExpanded()"
      >
        <q-icon v-if="isLeaf" :name="icons.circle" size="7px" />
        <q-icon v-else :name="isExpanded ? icons.menuDown : icons.menuRight" size="22px" />
      </q-btn>
    </div>
    <q-item-section no-wrap>
      <q-item-label class="q-ml-md text-no-wrap">
        <router-link class="wrapper-link" :to="`/components/${address}`">
          {{ address.isRoot ? 'Components' : component.name }}
        </router-link>
      </q-item-label>
    </q-item-section>
    <q-item-section side>
      <div class="items-center row">
        <alerts-indicator :address class="q-mr-xs" />
        <status-badge :address />
      </div>
    </q-item-section>
  </q-item>
  <div v-if="!isLeaf && isExpanded">
    <app-layout-drawer-component
      v-for="subcomponent in component.components"
      :key="subcomponent.name"
      :address="address.append(subcomponent.name)"
      :component="subcomponent"
    />
  </div>
</template>

<style module>
.root {
  min-height: 38px;
}

.toggleButton {
  margin-left: -16px;
}

.iconContainer {
  min-width: 40px;
}
</style>
