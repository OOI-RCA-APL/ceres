import { useAuth } from '@/api/auth'

// Authentication resolves before the first navigation so the auth middleware sees the
// real user rather than a logged-out default.
export default defineNuxtPlugin(async () => {
  await useAuth().refresh()
})
