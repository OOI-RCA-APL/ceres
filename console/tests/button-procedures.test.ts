import { describe, expect, it } from 'vitest'

import { type ProcedureInfo, isButtonProcedure, procedureNamespace } from '@/api/components'

function procedure(
  type: 'query' | 'action',
  output: ProcedureInfo['output'] = { type: 'value', json_schema: {} },
): ProcedureInfo {
  return {
    name: 'read',
    type,
    live: false,
    permissions: 'view',
    arguments: { json_schema: { type: 'object', properties: {} }, required: false },
    output,
  } as ProcedureInfo
}

describe('what a workspace button can run', () => {
  it('runs any action and a query returning a value', () => {
    expect(isButtonProcedure(procedure('action'))).toBe(true)
    expect(isButtonProcedure(procedure('query'))).toBe(true)
  })

  it('leaves out a query returning a stream or a file, which it has nowhere to show', () => {
    expect(isButtonProcedure(procedure('query', { type: 'streaming', media: 'video/mp4' }))).toBe(
      false,
    )
    expect(isButtonProcedure(procedure('query', { type: 'file', media: null }))).toBe(false)
  })

  it('names the kind of procedure in its path', () => {
    expect(procedureNamespace(procedure('query'))).toBe('queries')
    expect(procedureNamespace(procedure('action'))).toBe('actions')
    expect(procedureNamespace(null)).toBe('actions')
  })
})
