import type { InjectionKey } from 'vue'

import type { WidgetDrop } from '@/widget-drop'
import type { WorkspaceContext } from '@/workspace/edit-session'

export const workspaceInjectionKey: InjectionKey<WorkspaceContext> = Symbol('workspace')
export const widgetDropInjectionKey: InjectionKey<WidgetDrop> = Symbol('widget-drop')
