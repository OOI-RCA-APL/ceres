import { cloneDeep } from 'lodash-es'
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
  V extends FormFieldValidators<T> = FormFieldValidators<T>,
> = {
  editing?: boolean
  data: T | (() => T)
  validators?: V | ((data: T) => V)
  onSubmit?: (data: T) => Promise<FormState | undefined> | Promise<void>
}

/** A form's editing state machine: a working copy, the stored copy an edit resets to, and a
validation state derived from the field validators. */
export type Form<T extends FormData, V extends FormFieldValidators<T> = FormFieldValidators<T>> = {
  state: FormState
  editable: boolean
  readonly: boolean
  validation: FormValidationState
  readonly data: T
  readonly stored: T
  validators: V
  reset: () => void
  validate: () => Promise<void>
  submit: () => void | Promise<void>
  edit: () => void
  discard: () => void
  done: (data?: Partial<T> | null | undefined) => void
  load: (data: Partial<T> | null | undefined) => Form<T, V>
}

export function useForm<
  T extends FormData,
  V extends FormFieldValidators<T> = FormFieldValidators<T>,
>({ ...options }: FormOptions<T, V>): Readonly<Form<T, V>> {
  options.editing ??= true

  const data = reactive(
    cloneDeep(typeof options.data === 'object' ? options.data : options.data()),
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
    reset,
    validate,
    submit,
    edit,
    discard,
    done,
    load,
  }) as Form<T, V>

  let validations = $ref(0)

  function reset() {
    if (form.state === 'viewing') {
      form.validation = 'none'
    } else {
      form.state = 'editing'
      form.validation = 'validating'
    }

    form.load(form.stored)
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
      const validator = form.validators[field] as
        ((input: T[keyof T]) => FormFieldValidationResult) | undefined
      if (validator == null) {
        continue
      }

      const result = await validator(value)

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
        form.stored[key as keyof T] = cloneDeep(data[key as keyof T]) as T[keyof T]
        form.data[key as keyof T] = cloneDeep(data[key as keyof T]) as T[keyof T]
      }
    }

    return form
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
