<template>
  <div :class="[$style.root, 'q-pb-lg']">
    <q-spinner-ball color="primary" size="40px" />
  </div>
</template>

<style lang="scss" module>
.root {
  align-items: center;
  display: flex;
  animation: fadeIn 1s ease-in;
  justify-content: center;
  height: calc(100vh - 64px);
}

@keyframes fadeIn {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}
</style>
