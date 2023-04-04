<template>
  <div :class="['full-width', 'q-pb-lg', 'window-height', $style.root]">
    <q-spinner-ball color="primary" size="40px" />
  </div>
</template>

<style module>
.root {
  align-items: center;
  display: flex;
  animation: fadeIn 1s ease-in;
  justify-content: center;
  padding-bottom: 50vh;
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
