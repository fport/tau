/** D1 helpers. */

/** Whether a D1 error is a primary key / UNIQUE conflict (the row exists already). */
export function isUniqueViolation(err: unknown): boolean {
  return err instanceof Error && /UNIQUE constraint failed/i.test(err.message);
}
