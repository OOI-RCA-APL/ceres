<template>
  <div class="items-center row text-center">
    <div class="q-pa-sm">
      <div :class="[ledClass, 'self-led']" :style="zoomStyle"></div>
    </div>
    <div class="text-body1">{{ info.label }}</div>
  </div>
</template>

<script lang="ts" setup>
import { IndicatorElementInfo } from '@/element'

const { info } = defineProps<{
  info: IndicatorElementInfo
}>()

const isTriggered = $computed(() => (info.reversed ? !info.value : info.value))
const ledClass = $computed(() => 'self-led-' + (isTriggered ? info.color : 'off'))
const zoomStyle = $computed(() => `zoom: ${info.size ? sizes[info?.size] : sizes['md']}`)

const sizes = {
  xxs: 2,
  xs: 3,
  sm: 4,
  md: 5,
  lg: 6,
  xl: 7,
  xxl: 8,
}
</script>

<style lang="scss" scoped>
.self-led-green {
  background-image: -webkit-linear-gradient(top, #13fb04 0%, #58e343 50%, #aded99 100%);
}

.self-led-orange {
  background-image: -webkit-linear-gradient(top, #f9a004 0%, #e0ac45 50%, #ead698 100%);
}

.self-led-yellow {
  background-image: -webkit-linear-gradient(top, #f9d804 0%, #e0ce45 50%, #eade98 100%);
}

.self-led-red {
  background-image: -webkit-linear-gradient(top, #fb1304 0%, #e35843 50%, #edad99 100%);
}

.self-led-blue {
  background-image: -webkit-linear-gradient(top, #0408fb 0%, #4353e3 50%, #999fed 100%);
}

.self-led-off {
  background-image: -webkit-linear-gradient(top, #e2e1e0 0%, #bebebe 50%, #efeeee 100%);
}

.self-led {
  border-radius: 5px;
  width: 5px;
  // width: 10px;
  height: 5px;
  // height: 10px;
  // box-shadow: 0px 0px 1px black;
  border: 0.2px solid grey;
  // box-shadow: 0px 0px 2px black;
  zoom: 5;
}

.self-led:after {
  display: block;
  content: '';
  margin-left: 1px;
  margin-right: 1px;
  width: 3px;
  height: 2px;
  // width: 8px;
  // height: 6px;
  border-top-right-radius: 4px 3px;
  border-top-left-radius: 4px 3px;
  border-bottom-right-radius: 4px 3px;
  border-bottom-left-radius: 4px 3px;
  -webkit-border-top-right-radius: 4px 3px;
  -webkit-border-top-left-radius: 4px 3px;
  -webkit-border-bottom-right-radius: 4px 3px;
  -webkit-border-bottom-left-radius: 4px 3px;
  background-image: -webkit-linear-gradient(
    top,
    rgba(255, 255, 255, 0.8) 0%,
    rgba(255, 255, 255, 0.2) 100%
  );
}
</style>
