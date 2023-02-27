<template>
  <div class="full-width items-center justify-center q-pb-lg self-page-spinner-root window-height">
    <q-spinner-ball color="primary" size="40px" />
  </div>
</template>

<style lang="scss" scoped>
.self-page-spinner-root {
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
