import { ref } from 'vue'

export type FileDrop = ReturnType<typeof useFileDrop>

/** Accept files dragged onto an element, and track whether a drag is currently over it.
 *
 * Drag events fire again for every child element the pointer crosses, so entering and leaving are
 * counted rather than toggled. Without the count, moving over a child fires a leave on the parent
 * and the highlight flickers off while the pointer is still inside.
 *
 * @param onDrop Called with the dropped files, which is never empty.
 * @param accept Matches a file that should be taken, defaulting to every file.
 */
export function useFileDrop(
  onDrop: (files: File[]) => void | Promise<void>,
  accept: (file: File) => boolean = () => true
) {
  const active = ref(false)
  let depth = 0

  function carriesFiles(event: DragEvent): boolean {
    return event.dataTransfer?.types.includes('Files') === true
  }

  function onDragEnter(event: DragEvent) {
    if (!carriesFiles(event)) {
      return
    }

    depth += 1
    active.value = true
  }

  function onDragOver(event: DragEvent) {
    if (!carriesFiles(event)) {
      return
    }

    // Without this the browser navigates to the dropped file instead of handing it over.
    event.preventDefault()
    if (event.dataTransfer != null) {
      event.dataTransfer.dropEffect = 'copy'
    }
  }

  function onDragLeave() {
    depth = Math.max(0, depth - 1)
    if (depth === 0) {
      active.value = false
    }
  }

  function reset() {
    depth = 0
    active.value = false
  }

  async function onDropFiles(event: DragEvent) {
    if (!carriesFiles(event)) {
      return
    }

    event.preventDefault()
    reset()

    const files = [...(event.dataTransfer?.files ?? [])].filter(accept)
    if (files.length > 0) {
      await onDrop(files)
    }
  }

  return {
    active,
    handlers: {
      onDragenter: onDragEnter,
      onDragover: onDragOver,
      onDragleave: onDragLeave,
      onDrop: onDropFiles,
    },
  }
}

/** Whether a file looks like an exported workspace, which is the only kind the console imports. */
export function isWorkspaceFile(file: File): boolean {
  return file.type === 'application/json' || file.name.endsWith('.json')
}
