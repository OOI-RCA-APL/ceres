import { FormFieldValidationResult } from '@/form'
import _ from 'lodash'
import Validator from 'validator'

export function isUsername(input: unknown): boolean {
  return input != null && typeof input === 'string' && input.match(/^[a-zA-Z0-9_.-]+$/) != null
}

export function isEmail(input: unknown): boolean {
  return input != null && typeof input === 'string' && Validator.isEmail(input)
}

export function isNotNull(input: unknown): boolean {
  return input != null
}

export function isNotEmpty(input: unknown): boolean {
  return input != null && (typeof input === 'string' || _.isArrayLike(input)) && input.length > 0
}

export function isNotBlank(input: unknown): boolean {
  return input != null && typeof input === 'string' && input.trim() !== ''
}

export function isPositive(input: unknown): boolean {
  return typeof input === 'number' && input >= 0
}

export function isNot(input: unknown, value: unknown): boolean {
  return input !== value
}

export function isNotIn(input: unknown, values: unknown[]): boolean {
  return !values.includes(input)
}

function createValidator<T>(
  check: (input: T) => boolean
): (message?: string) => (input: T) => FormFieldValidationResult {
  return (message) => (input) => check(input) || message || false
}

function createValidatorWithArgument<T, A>(
  check: (input: T, argument: A) => boolean
): (argument: A, message: string) => (input: T) => FormFieldValidationResult {
  return (argument, message) => (input) => check(input, argument) || message
}

export function useValidate() {
  return {
    accept: () => () => true,
    isUsername: createValidator(isUsername),
    isEmail: createValidator(isEmail),
    isNotNull: createValidator(isNotNull),
    isNotEmpty: createValidator(isNotEmpty),
    isNotBlank: createValidator(isNotBlank),
    isPositive: createValidator(isPositive),
    isNot: createValidatorWithArgument(isNot),
    isNotIn: createValidatorWithArgument(isNotIn),
  }
}

export type Validate = ReturnType<typeof useValidate>
