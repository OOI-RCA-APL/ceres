import { defineStore } from 'pinia'

import { Address, engineRoot } from '@/api/address'
import { useAuth } from '@/api/auth'
import type { WorkspaceMove } from '@/components/c-workspace-move-dialog.vue'
import { useDialogs } from '@/dialogs'
import { useNavigation } from '@/navigation'
import { useNotify } from '@/notify'
import { workspaceQueryKey } from '@/tabs'
import { useWorkspaces, type Workspace, type WorkspaceData } from '@/workspace'
import { pinWidgetAddresses } from '@/workspace/association'

/** Moving a workspace to Global or a component, from every place that offers it. */
export const useWorkspaceMove = defineStore('workspace-move', () => {
  const auth = useAuth()
  const dialogs = useDialogs()
  const navigation = useNavigation()
  const notify = useNotify()
  const workspaces = useWorkspaces()

  function pageOf(location: string) {
    return location === engineRoot ? '/' : `/components/${location}`
  }

  async function apply({ workspace, destination, copy, isPrivate }: WorkspaceMove) {
    const scope = Address.parse(destination)
    // A copy is of what the caller sees, which is their pending edit when they hold one.
    const shown = copy ? ((await workspaces.getEdit(workspace.id))?.data ?? workspace.data) : null
    const result =
      shown != null
        ? await workspaces.create({
            name: workspace.name,
            scope,
            owner_id: isPrivate ? (auth.user?.id ?? null) : null,
            // A copy is a new workspace, so its relative addresses are pinned here. Moving the
            // workspace itself has the server pin them, including those hidden from the caller.
            // Parsed again on the way out, so the raw JSON stands in for parsed data here.
            data: pinWidgetAddresses(shown, workspace.scope) as unknown as WorkspaceData,
          })
        : await workspaces.update(workspace.id, { scope })

    announce(workspace.name, result.id, destination, copy)
  }

  /** Report a workspace moved or copied, offering the way to it when that is off this page. */
  function announce(name: string, id: string, destination: string, copy: boolean) {
    const where = destination === engineRoot ? 'Global' : destination
    const message = copy ? `Copied "${name}" to ${where}.` : `Moved "${name}" to ${where}.`

    // Landing anywhere but the page being viewed takes it out of sight, so the notice offers the
    // way to it.
    const here = navigation.component ?? (navigation.route.path === '/' ? engineRoot : null)
    if (here === destination) {
      notify.success(message)
      return
    }

    notify.success(message, {
      duration: 6000,
      actions: [
        {
          label: 'Open',
          onClick: () =>
            void navigation.go({
              path: pageOf(destination),
              query: { [workspaceQueryKey]: id },
            }),
        },
      ],
    })
  }

  /** Ask where a workspace goes and whether it is copied, then do it.

  Without a workspace the dialog asks which of `candidates`. A destination already decided, by a
  drop or by the page asking, skips the choice of location.
  */
  function move(options: {
    workspace?: Workspace
    candidates?: Workspace[]
    destination?: string
  }) {
    dialogs.moveWorkspace(options).onOk((chosen) => {
      apply(chosen).catch((error: unknown) => {
        console.error(error)
        notify.error(
          chosen.copy ? 'Failed to copy the workspace.' : 'Failed to move the workspace.',
        )
      })
    })
  }

  return { move, announce }
})
