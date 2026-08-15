import type * as z from 'zod'

export class CommonError extends Error {}
export class NotFoundError extends CommonError {
  constructor(
    public resourceType: string,
    message?: string,
  ) {
    super(message)
  }
}
export class Escape extends CommonError {
  constructor() {
    super('Escape')
  }
}

export class Failure extends CommonError {
  constructor(public error: ErrorInfo) {
    super(error.type)
  }
}

export type GuardErrorHandler = (error: ErrorInfo) => unknown
export type GuardMatch = {
  type: ErrorType
  do: GuardErrorHandler
}
export type GuardMapping = Partial<Record<ErrorType, GuardErrorHandler>>

export function escape(): never {
  throw new Escape()
}

export type ErrorHandling = GuardErrorHandler | GuardMapping | (GuardMatch | GuardErrorHandler)[]

export async function guard<T>(promise: Promise<T>, handling: ErrorHandling): Promise<T> {
  if (typeof handling === 'function') {
    handling = [handling]
  } else if (!Array.isArray(handling)) {
    handling = (Object.entries(handling) as [ErrorType, GuardErrorHandler][]).map(
      ([type, handler]) => ({ type, do: handler }),
    )
  }

  try {
    return await promise
  } catch (exception) {
    if (exception instanceof Failure) {
      for (const current of handling) {
        if (typeof current === 'function') {
          await current(exception.error)
          escape()
        }
        if (exception.error.type === current.type) {
          await current.do(exception.error)
          escape()
        }
      }
    }

    throw exception
  }
}

export type ErrorType =
  | 'non-json-response-error'
  | 'response-parse-error'
  | 'not-found-error'
  | 'already-exists-error'
  | 'bad-credentials-error'
  | 'validation-failed-error'

type BaseErrorInfo = {
  __error__: true
}

export type ErrorInfo = BaseErrorInfo &
  (
    | { type: 'not-found-error' }
    | { type: 'already-exists-error'; field: string }
    | { type: 'non-json-response-error'; message: string }
    | { type: 'response-parse-error'; issues: z.core.$ZodIssue[] }
    | { type: string }
  )
