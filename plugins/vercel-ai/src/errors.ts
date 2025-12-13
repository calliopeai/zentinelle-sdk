/**
 * Error types for Zentinelle Vercel AI integration.
 */

export interface PolicyResult {
  allowed: boolean;
  reason?: string;
  warnings: string[];
}

export class PolicyViolationError extends Error {
  result: PolicyResult;

  constructor(message: string, result: PolicyResult) {
    super(message);
    this.name = 'PolicyViolationError';
    this.result = result;
  }
}
