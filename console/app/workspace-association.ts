import { defineStore } from 'pinia'

import { Address, engineRoot } from '@/api/address'
import { useAuth } from '@/api/auth'
import type { WorkspaceAssociation } from '@/components/c-workspace-associate-dialog.vue'
import { useDialogs } from '@/dialogs'
import { useNavigation } from '@/navigation'
import { useNotify } from '@/notify'
import { workspaceQueryKey } from '@/tabs'
import { useWorkspaces, type Workspace, type WorkspaceData } from '@/workspace'
import { pinWidgetAddresses } from '@/workspace/association'

/** Changing which component a workspace is associated with, from every place that offers it. */
export const useWorkspaceAssociation = defineStore('workspace-association', () => {
  const auth = useAuth()
  const dialogs = useDialogs()
  const navigation = useNavigation()
  const notify = useNotify()
  const workspaces = useWorkspaces()

  function pageOf(placement: string) {
    return placement === engineRoot ? '/' : `/components/${placement}`
  }

  async function apply({ workspace, destination, mode, isPrivate }: WorkspaceAssociation) {
    const scope = Address.parse(destination)
    const result =
      mode === 'copy'
        ? await workspaces.create({
            name: workspace.name,
            scope,
            owner_id: isPrivate ? (auth.user?.id ?? null) : null,
            // A copy is a new workspace, so its relative addresses are pinned here. Changing the
            // workspace itself has the server pin them, including those hidden from the caller.
            // Parsed again on the way out, so the raw JSON stands in for parsed data here.
            data: pinWidgetAddresses(workspace.data, workspace.scope) as unknown as WorkspaceData,
          })
        : await workspaces.update(workspace.id, { scope })

    announce(workspace.name, result.id, destination, mode)
  }

  /** Report a workspace placed elsewhere, offering the way to it when that is off this page. */
  function announce(name: string, id: string, destination: string, mode: 'change' | 'copy') {
    const where = destination === engineRoot ? 'Home' : destination
    let message = `Copied "${name}" to ${where}.`
    if (mode === 'change') {
      message =
        destination === engineRoot
          ? `"${name}" is now global.`
          : `"${name}" is now associated with ${destination}.`
    }

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

  /** Ask where a workspace goes and whether it moves or is copied, then do it.

  Without a workspace the dialog asks which of `candidates`. A destination already decided, by a
  drop or by the page asking, skips the choice of component.
  */
  function associate(options: {
    workspace?: Workspace
    candidates?: Workspace[]
    destination?: string
  }) {
    dialogs.associateWorkspace(options).onOk((association) => {
      apply(association).catch((error: unknown) => {
        console.error(error)
        notify.error(
          association.mode === 'copy'
            ? 'Failed to copy the workspace.'
            : 'Failed to change where the workspace belongs.',
        )
      })
    })
  }

  return { associate, announce }
})
