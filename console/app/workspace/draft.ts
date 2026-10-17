import { deepClone, isStructurallyEqual } from '@/utilities'
import { comparableWorkspaceData, type WorkspaceData } from '@/workspace/models'

/** What a tab's working copy last agreed on with the user's draft on the server.

Every tab the user has open on a workspace edits the same draft. A tab writes only an edit of its
own, so reloading or closing one never puts its older copy over a draft another tab wrote since,
and a tab with no edit of its own takes a newer draft when it next comes into view. Two tabs that
both hold edits still to write each write their own, and the last to write wins. */
export class DraftSync {
  #agreed: WorkspaceData | null = null

  /** Records `data` as what the server holds, once loaded from it or written to it. */
  agree(data: WorkspaceData | null) {
    this.#agreed = data == null ? null : (deepClone(data) as WorkspaceData)
  }

  /** Whether `data` holds an edit this tab has not written yet. */
  isUnsaved(data: WorkspaceData | null) {
    return data != null && (this.#agreed == null || !same(data, this.#agreed))
  }

  /** What the tab shows instead of `data` once the server holds `server`, or null to keep `data`.

  An edit of the tab's own wins until it is written, and the tab's next write takes it to the
  server whatever another tab wrote meanwhile. */
  incoming(data: WorkspaceData | null, server: WorkspaceData | null) {
    if (data == null || server == null || this.isUnsaved(data) || same(data, server)) {
      return null
    }

    return deepClone(server) as WorkspaceData
  }
}

function same(left: WorkspaceData, right: WorkspaceData) {
  return isStructurallyEqual(comparableWorkspaceData(left), comparableWorkspaceData(right))
}
