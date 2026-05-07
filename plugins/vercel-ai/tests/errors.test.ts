import { describe, it, expect } from 'vitest';
import { PolicyViolationError } from '../src/errors';

describe('PolicyViolationError', () => {
  it('should extend Error', () => {
    const result = { allowed: false, reason: 'blocked', warnings: [] };
    const error = new PolicyViolationError('blocked by policy', result);
    expect(error).toBeInstanceOf(Error);
  });

  it('should set name to PolicyViolationError', () => {
    const result = { allowed: false, reason: 'rate limit', warnings: [] };
    const error = new PolicyViolationError('rate limit exceeded', result);
    expect(error.name).toBe('PolicyViolationError');
  });

  it('should store the policy result', () => {
    const result = {
      allowed: false,
      reason: 'tool not permitted',
      warnings: ['approaching limit'],
    };
    const error = new PolicyViolationError('tool blocked', result);
    expect(error.result).toEqual(result);
    expect(error.result.allowed).toBe(false);
    expect(error.result.reason).toBe('tool not permitted');
    expect(error.result.warnings).toEqual(['approaching limit']);
  });

  it('should set the error message', () => {
    const result = { allowed: false, warnings: [] };
    const error = new PolicyViolationError('custom message', result);
    expect(error.message).toBe('custom message');
  });

  it('should handle result without reason', () => {
    const result = { allowed: false, warnings: [] };
    const error = new PolicyViolationError('blocked', result);
    expect(error.result.reason).toBeUndefined();
  });

  it('should have a stack trace', () => {
    const result = { allowed: false, warnings: [] };
    const error = new PolicyViolationError('test', result);
    expect(error.stack).toBeDefined();
    expect(error.stack).toContain('PolicyViolationError');
  });
});
