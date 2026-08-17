import { useAuth } from '@/api/auth'
import { getLoginRedirectPath, userCanAccess } from '@/navigation'
import { useNotify } from '@/notify'

export default defineNuxtRouteMiddleware((to) => {
  const auth = useAuth()
  if (userCanAccess(auth.user, to)) {
    return
  }

  useNotify().warn('You do not have access to that resource.')
  return navigateTo(getLoginRedirectPath(to.fullPath))
})
