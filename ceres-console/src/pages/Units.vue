<template>
  <div class="self-page">
    <div class="full-height overflow-auto scroll">
      <router-view />
    </div>
  </div>
</template>

<style lang="scss">
.self-page {
  height: calc(100vh - 50px);
}
</style>
