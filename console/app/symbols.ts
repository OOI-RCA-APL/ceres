import type { InjectionKey } from 'vue'

import type { RecordViewContext } from '@/record-view'
import type { WidgetDrop } from '@/widget-drop'
import type { WorkspaceContext } from '@/workspace/edit-session'

export const workspaceInjectionKey: InjectionKey<WorkspaceContext> = Symbol('workspace')
export const widgetDropInjectionKey: InjectionKey<WidgetDrop> = Symbol('widget-drop')
export const recordViewContextInjectionKey: InjectionKey<RecordViewContext> =
  Symbol('record-view-context')
