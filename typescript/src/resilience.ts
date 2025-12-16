/**
 * Resilience utilities: retry logic and circuit breaker.
 */

export interface RetryConfigOptions {
  maxRetries?: number;
  baseDelay?: number;
  maxDelay?: number;
  exponentialBase?: number;
  jitter?: boolean;
}

export class RetryConfig {
  maxRetries: number;
  baseDelay: number;
  maxDelay: number;
  exponentialBase: number;
  jitter: boolean;

  constructor(options: RetryConfigOptions = {}) {
    this.maxRetries = options.maxRetries ?? 3;
    this.baseDelay = options.baseDelay ?? 1000;
    this.maxDelay = options.maxDelay ?? 60000;
    this.exponentialBase = options.exponentialBase ?? 2;
    this.jitter = options.jitter ?? true;
  }

  getDelay(attempt: number): number {
    let delay = this.baseDelay * Math.pow(this.exponentialBase, attempt);
    delay = Math.min(delay, this.maxDelay);

    if (this.jitter) {
      const jitterRange = delay * 0.25;
      delay += Math.random() * jitterRange * 2 - jitterRange;
    }

    return Math.max(0, delay);
  }
}

type CircuitState = 'closed' | 'open' | 'half_open';

export interface CircuitBreakerOptions {
  failureThreshold?: number;
  recoveryTimeout?: number;
  halfOpenMaxCalls?: number;
}

export class CircuitBreaker {
  private failureThreshold: number;
  private recoveryTimeout: number;
  private halfOpenMaxCalls: number;

  private state: CircuitState = 'closed';
  private failureCount = 0;
  private lastFailureTime: number | null = null;
  private halfOpenCalls = 0;

  constructor(options: CircuitBreakerOptions = {}) {
    this.failureThreshold = options.failureThreshold ?? 5;
    this.recoveryTimeout = options.recoveryTimeout ?? 30000;
    this.halfOpenMaxCalls = options.halfOpenMaxCalls ?? 3;
  }

  getState(): CircuitState {
    if (this.state === 'open') {
      const now = Date.now();
      if (this.lastFailureTime && now - this.lastFailureTime > this.recoveryTimeout) {
        this.state = 'half_open';
        this.halfOpenCalls = 0;
      }
    }
    return this.state;
  }

  recordSuccess(): void {
    if (this.state === 'half_open') {
      this.halfOpenCalls++;
      if (this.halfOpenCalls >= this.halfOpenMaxCalls) {
        this.state = 'closed';
        this.failureCount = 0;
      }
    } else if (this.state === 'closed') {
      this.failureCount = 0;
    }
  }

  recordFailure(): void {
    this.failureCount++;
    this.lastFailureTime = Date.now();

    if (this.state === 'half_open') {
      this.state = 'open';
    } else if (this.failureCount >= this.failureThreshold) {
      this.state = 'open';
    }
  }

  canExecute(): boolean {
    return this.getState() !== 'open';
  }
}
