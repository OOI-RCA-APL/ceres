export class AppError extends Error {}
export class NotFoundError extends AppError {
  constructor(public resourceType: string, message?: string) {
    super(message)
  }
}
