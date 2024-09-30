import type { InjectionKey } from 'vue'

import type { InterfaceContext } from '@/interface'
import type { PanelGroup } from '@/panel-group'
import { RecordViewContext } from '@/record-view'
import type { SchemaForm } from '@/schema-form'
import { WorkspaceContext } from '@/workspace'

export const schemaFormInjectionKey: InjectionKey<SchemaForm> = Symbol('schema-form')
export const panelGroupInjectionKey: InjectionKey<PanelGroup> = Symbol('panel-group')
export const recordViewContextInjectionKey: InjectionKey<RecordViewContext> =
  Symbol('record-view-context')
export const interfaceContextInjectionKey: InjectionKey<InterfaceContext> =
  Symbol('interface-context')
export const unset = Symbol('unset')
export const workspaceInjectionKey: InjectionKey<WorkspaceContext> = Symbol('workspace')
