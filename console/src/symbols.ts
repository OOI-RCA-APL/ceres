import type { InterfaceContext } from '@/interface'
import type { PanelGroup } from '@/panel-group'
import type { SchemaForm } from '@/schema-form'
import type { InjectionKey } from 'vue'

export const schemaFormInjectionKey: InjectionKey<SchemaForm> = Symbol('schema-form')
export const panelGroupInjectionKey: InjectionKey<PanelGroup> = Symbol('panel-group')
export const interfaceContextInjectionKey: InjectionKey<InterfaceContext> =
  Symbol('interface-context')
export const unset = Symbol('unset')
