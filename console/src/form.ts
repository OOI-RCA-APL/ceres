import { cloneDeep } from 'lodash-es'
import { QForm, QInput } from 'quasar'
import { reactive, watch, watchEffect } from 'vue'

export type FormState = 'viewing' | 'editing' | 'submitting' | 'submitted'
export type FormValidationState = 'none' | 'validating' | 'valid' | 'invalid'
export type FormData = Record<string, unknown>
export type FormFieldValidators<T> = {
  [K in keyof T]?: FormFieldValidator<T, K>
}
export type FormFieldValidator<T, K extends keyof T> = (value: T[K]) => FormFieldValidationResult
export type FormFieldValidationResult = string | boolean | Promise<string | boolean>

export type FormOptions<
  T extends FormData,
  V extends FormFieldValidators<T> = FormFieldValidators<T>
> = {
  editing?: boolean
  data: T | (() => T)
  validators?: V | ((data: T) => V)
  onSubmit?: (data: T) => Promise<FormState | void>
}

export type Form<T extends FormData, V extends FormFieldValidators<T> = FormFieldValidators<T>> = {
  state: FormState
  editable: boolean
  readonly: boolean
  validation: FormValidationState
  readonly data: T
  readonly stored: T
  validators: V
  bind: (form: any) => void
  getInputs(): QInput[]
  getInput(name: string): QInput | null
  focus: (name?: string | null | undefined) => void
  reset: () => void
  validate: () => Promise<void>
  submit: () => void | Promise<void>
  edit: () => void
  discard: () => void
  done: (data?: Partial<T> | null | undefined) => void
  load: (data: Partial<T> | null | undefined) => Form<T, V>
  check: (field: keyof T) => void | Promise<void>
}

export function useForm<
  T extends FormData,
  V extends FormFieldValidators<T> = FormFieldValidators<T>
>({ ...options }: FormOptions<T, V>): Readonly<Form<T, V>> {
  options.editing ??= true

  const data = reactive(
    cloneDeep(typeof options.data === 'object' ? options.data : options.data())
  ) as T

  const stored = reactive(cloneDeep(data)) as T

  const validators: V = (() => {
    if (options.validators == null) {
      return {} as V
    }
    if (typeof options.validators === 'object') {
      return options.validators
    }

    return options.validators(data)
  })()

  const editing = options.editing ?? true
  const form = reactive<Form<T, V>>({
    state: editing ? 'editing' : 'viewing',
    editable: editing,
    readonly: !editing,
    validation: 'none',
    data: data,
    stored: stored,
    validators,
    bind,
    getInputs,
    getInput,
    focus,
    reset,
    validate,
    submit,
    edit,
    discard,
    done,
    load,
    check,
  }) as Form<T, V>

  let validations = $ref(0)
  let component = $ref<QForm | null>(null)

  function bind(instance: QForm) {
    component = instance
  }

  function getInputs(): QInput[] {
    return component?.getValidationComponents() ?? ([] as any)
  }

  function getInput(name?: string): QInput | null {
    return getInputs().find((component) => component.name === name) ?? null
  }

  function focus(name?: string | null | undefined) {
    if (name != null) {
      getInput(name)?.focus()
    } else {
      component?.focus()
    }
  }

  function reset() {
    if (form.state === 'viewing') {
      form.validation = 'none'
    } else {
      form.state = 'editing'
      form.validation = 'validating'
    }

    form.load(form.stored)
    component?.resetValidation()
    component?.reset()
  }

  async function validate() {
    if (form.state === 'viewing') {
      return
    }

    form.validation = 'validating'
    const previousValidationCount = ++validations
    let isValid = true

    for (const key of Object.keys(form.validators as FormFieldValidators<T>)) {
      const field = key as keyof T
      const value = form.data[field]
      const validator = form.validators[field]
      if (validator == null) {
        continue
      }

      const result = await validator(value as any)

      if (typeof result === 'string' || (typeof result === 'boolean' && !result)) {
        isValid = false
      }
    }

    if (validations === previousValidationCount) {
      form.validation = isValid ? 'valid' : 'invalid'
    }
  }

  async function submit() {
    if (form.state !== 'editing' || form.validation !== 'valid' || options.onSubmit == null) {
      return
    }

    try {
      form.state = 'submitting'
      const state = (await options.onSubmit(form.data)) as FormState | undefined
      if (state != null) {
        form.state = state
      } else if (form.state === 'submitting') {
        form.state = 'editing'
      }
    } catch (error) {
      form.state = 'editing'
      throw error
    }
  }

  function edit() {
    form.state = 'editing'
    form.reset()
  }

  function discard() {
    form.state = 'viewing'
    form.reset()
  }

  function done(data: Partial<T> | null | undefined = null) {
    form.state = 'viewing'
    form.load(data ?? form.stored)
    form.reset()
  }

  function load(data: Partial<T> | null | undefined): Form<T, V> {
    if (data == null) {
      return form
    }

    for (const key of Object.keys(form.data)) {
      if (key in data) {
        form.stored[key as keyof T] = cloneDeep(data[key]) as any
        form.data[key as keyof T] = cloneDeep(data[key]) as any
      }
    }

    return form
  }

  async function check(field: keyof V) {
    if (form.state === 'viewing') {
      return
    }

    if (component != null) {
      const validator = form.validators[field]
      const children = component.getValidationComponents()
      for (const child of children) {
        const rules = (child as any).rules as unknown[]
        if (typeof rules === 'object') {
          if (rules.includes(validator)) {
            await child.validate('')
          }
        }
      }
    }
  }

  watchEffect(() => {
    form.editable = form.state === 'editing'
    form.readonly = form.state !== 'editing'
  })

  watch([() => form.state, form.data], form.validate, {
    immediate: true,
  })

  return form
}
