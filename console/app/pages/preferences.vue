<script lang="ts" setup>
import { computed } from 'vue'

import { usePreferences } from '@/preferences'
import { displayDuration, duration } from '@/time'

const preferences = usePreferences()
const isDevelopment = import.meta.dev

// Carried as seconds because the select matches an item by value, and two `Duration` objects
// built from the same length are never the same object.
const statisticsDurationItems = [60, 5 * 60, 30 * 60, 3600, 12 * 3600, 86400].map((seconds) => ({
  label: displayDuration(duration(seconds, 'seconds')),
  value: seconds,
}))

const statisticsSeconds = computed({
  get: () => preferences.statisticsDuration.asSeconds(),
  set: (seconds: number) => (preferences.statisticsDuration = duration(seconds, 'seconds')),
})
</script>

<template>
  <c-card-page title="Preferences">
    <template #subtitle>
      <c-text class="mx-4 mb-2 block" variant="description">
        Saved in this browser, so each browser keeps its own.
      </c-text>
    </template>

    <c-preference-row description="Use the dark theme across the console." label="Dark Mode">
      <c-switch v-model="preferences.isDarkModeEnabled" aria-label="Dark Mode" />
    </c-preference-row>

    <template #sections>
      <c-card-page-section title="Workspaces">
        <c-preference-row
          description="Ask before committing changes to a private workspace. Shared workspaces always ask, since everyone with access sees the commit."
          label="Confirm Private Commits"
        >
          <c-switch
            v-model="preferences.isPrivateCommitConfirmationEnabled"
            aria-label="Confirm Private Commits"
          />
        </c-preference-row>
      </c-card-page-section>

      <c-card-page-section title="Statistics">
        <c-preference-row
          description="The time over which statistics, like alert counts, are calculated."
          label="Duration"
        >
          <c-select
            v-model="statisticsSeconds"
            aria-label="Statistics Duration"
            class="w-32"
            :items="statisticsDurationItems"
          />
        </c-preference-row>
      </c-card-page-section>

      <c-card-page-section v-if="isDevelopment" title="Development">
        <c-preference-row
          description="Show the developer tools at the foot of the drawer."
          label="Developer Mode"
        >
          <c-switch v-model="preferences.isDeveloperModeEnabled" aria-label="Developer Mode" />
        </c-preference-row>
      </c-card-page-section>
    </template>
  </c-card-page>
</template>
