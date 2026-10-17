import { describe, expect, it } from 'vitest'

import { DraftSync } from '@/workspace/draft'
import { WorkspaceDataModel, type WorkspaceData } from '@/workspace/models'

function layout(...names: string[]): WorkspaceData {
  return WorkspaceDataModel.parse({
    layout: [{ height: 200, widgets: names.map((name) => ({ type: 'text', name, width: 1 })) }],
  })
}

describe('DraftSync', () => {
  it('writes nothing for a working copy as it was loaded', () => {
    const draft = new DraftSync()
    const loaded = layout('A')
    draft.agree(loaded)

    expect(draft.isUnsaved(loaded)).toBe(false)
  })

  it('writes an edit until the server holds it', () => {
    const draft = new DraftSync()
    draft.agree(layout('A'))
    const edited = layout('A', 'B')

    expect(draft.isUnsaved(edited)).toBe(true)
    draft.agree(edited)
    expect(draft.isUnsaved(edited)).toBe(false)
  })

  // A reload saves on the way out. Writing an older copy then would undo another tab's edits.
  it('never writes a copy older than a draft another tab wrote', () => {
    const draft = new DraftSync()
    const loaded = layout('A')
    draft.agree(loaded)

    const elsewhere = layout('A', 'B')
    expect(draft.isUnsaved(loaded)).toBe(false)
    expect(draft.incoming(loaded, elsewhere)).toEqual(elsewhere)
  })

  it('takes the newer draft, then writes nothing back for it', () => {
    const draft = new DraftSync()
    draft.agree(layout('A'))
    const next = draft.incoming(layout('A'), layout('A', 'B'))
    draft.agree(next)

    expect(draft.isUnsaved(next)).toBe(false)
  })

  it('keeps an edit of its own still to write over a newer draft', () => {
    const draft = new DraftSync()
    draft.agree(layout('A'))

    expect(draft.incoming(layout('A', 'C'), layout('A', 'B'))).toBeNull()
  })

  it('keeps a copy the server already matches', () => {
    const draft = new DraftSync()
    draft.agree(layout('A'))

    expect(draft.incoming(layout('A'), layout('A'))).toBeNull()
  })
})
