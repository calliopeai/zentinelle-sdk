/**
 * Error types for Zentinelle SDK.
 */

import type { EvaluateResult } from './types';

export class ZentinelleError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ZentinelleError';
  }
}

export class ZentinelleConnectionError extends ZentinelleError {
  constructor(message: string) {
    super(message);
    this.name = 'ZentinelleConnectionError';
  }
}

export class ZentinelleAuthError extends ZentinelleError {
  constructor(message: string) {
    super(message);
    this.name = 'ZentinelleAuthError';
  }
}

export class ZentinelleRateLimitError extends ZentinelleError {
  retryAfter: number;

  constructor(message: string, retryAfter: number = 60) {
    super(message);
    this.name = 'ZentinelleRateLimitError';
    this.retryAfter = retryAfter;
  }
}

export class PolicyViolationError extends ZentinelleError {
  result: EvaluateResult;

  constructor(message: string, result: EvaluateResult) {
    super(message);
    this.name = 'PolicyViolationError';
    this.result = result;
  }
}
