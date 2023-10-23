import type { SchemaForm } from '@/schema-form'
import type { PanelGroup } from '@/panel-group'
import { InjectionKey } from 'vue'

export const schemaFormInjectionKey: InjectionKey<SchemaForm> = Symbol('schema-form')
export const panelGroupInjectionKey: InjectionKey<PanelGroup> = Symbol('panel-group')
export const unset = Symbol('unset')
