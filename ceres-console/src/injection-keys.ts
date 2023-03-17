import type { SchemaForm } from '@/json-schema'
import type { PanelGroup } from '@/panel-group'
import { InjectionKey } from 'vue'

export const schemaFormInjectionKey: InjectionKey<SchemaForm> = Symbol('schema-form')
export const panelGroupInjectionKey: InjectionKey<PanelGroup> = Symbol('panel-group')
