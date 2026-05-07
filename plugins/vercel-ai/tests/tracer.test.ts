import { describe, it, expect, vi, beforeEach } from 'vitest';

// vi.hoisted ensures these are available when vi.mock factories run (hoisted above imports)
const { mockEmit, mockShutdown, mockClientConstructor } = vi.hoisted(() => {
  const mockEmit = vi.fn();
  const mockShutdown = vi.fn().mockResolvedValue(undefined);
  const mockClientConstructor = vi.fn().mockImplementation(() => ({
    emit: mockEmit,
    shutdown: mockShutdown,
  }));
  return { mockEmit, mockShutdown, mockClientConstructor };
});

vi.mock('zentinelle', () => ({
  ZentinelleClient: mockClientConstructor,
}));

import { ZentinelleTracer } from '../src/tracer';

describe('ZentinelleTracer', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('constructor', () => {
    it('should create a tracer with default options', () => {
      const tracer = new ZentinelleTracer({
        apiKey: 'sk_agent_test_key_123',
      });

      expect(tracer).toBeDefined();
      expect(mockClientConstructor).toHaveBeenCalledWith({
        apiKey: 'sk_agent_test_key_123',
        agentType: 'vercel-ai',
        endpoint: undefined,
      });
    });

    it('should accept custom agentType and endpoint', () => {
      new ZentinelleTracer({
        apiKey: 'sk_agent_test_key_123',
        agentType: 'custom-tracer',
        endpoint: 'https://my-zentinelle.example.com',
      });

      expect(mockClientConstructor).toHaveBeenCalledWith({
        apiKey: 'sk_agent_test_key_123',
        agentType: 'custom-tracer',
        endpoint: 'https://my-zentinelle.example.com',
      });
    });
  });

  describe('startTrace', () => {
    it('should create a trace and emit trace_start event', () => {
      const tracer = new ZentinelleTracer({
        apiKey: 'sk_agent_test_key_123',
      });

      const trace = tracer.startTrace('chat-completion');

      expect(trace).toBeDefined();
      expect(trace.id).toBeDefined();
      expect(typeof trace.id).toBe('string');
      expect(trace.id.length).toBeGreaterThan(0);
      expect(mockEmit).toHaveBeenCalledWith(
        'trace_start',
        expect.objectContaining({
          trace_id: trace.id,
          name: 'chat-completion',
        }),
        expect.objectContaining({ category: 'telemetry' })
      );
    });

    it('should pass attributes to trace_start event', () => {
      const tracer = new ZentinelleTracer({
        apiKey: 'sk_agent_test_key_123',
      });

      tracer.startTrace('model-request', { model: 'gpt-4o', tier: 'premium' });

      expect(mockEmit).toHaveBeenCalledWith(
        'trace_start',
        expect.objectContaining({
          attributes: { model: 'gpt-4o', tier: 'premium' },
        }),
        expect.anything()
      );
    });
  });

  describe('getTrace', () => {
    it('should return active trace by ID', () => {
      const tracer = new ZentinelleTracer({
        apiKey: 'sk_agent_test_key_123',
      });

      const trace = tracer.startTrace('test-trace');
      const retrieved = tracer.getTrace(trace.id);

      expect(retrieved).toBe(trace);
    });

    it('should return undefined for unknown trace ID', () => {
      const tracer = new ZentinelleTracer({
        apiKey: 'sk_agent_test_key_123',
      });

      const result = tracer.getTrace('nonexistent-id');
      expect(result).toBeUndefined();
    });
  });

  describe('endTrace', () => {
    it('should end trace and remove from active traces', () => {
      const tracer = new ZentinelleTracer({
        apiKey: 'sk_agent_test_key_123',
      });

      const trace = tracer.startTrace('test-trace');
      tracer.endTrace(trace.id);

      expect(tracer.getTrace(trace.id)).toBeUndefined();
    });

    it('should emit trace_end event', () => {
      const tracer = new ZentinelleTracer({
        apiKey: 'sk_agent_test_key_123',
      });

      const trace = tracer.startTrace('test-trace');
      mockEmit.mockClear();
      tracer.endTrace(trace.id);

      expect(mockEmit).toHaveBeenCalledWith(
        'trace_end',
        expect.objectContaining({
          trace_id: trace.id,
          name: 'test-trace',
          duration_ms: expect.any(Number),
        }),
        expect.objectContaining({ category: 'telemetry' })
      );
    });

    it('should handle ending nonexistent trace gracefully', () => {
      const tracer = new ZentinelleTracer({
        apiKey: 'sk_agent_test_key_123',
      });

      // Should not throw
      tracer.endTrace('nonexistent-id');
    });
  });

  describe('trace (wrapper)', () => {
    it('should wrap an async function with tracing', async () => {
      const tracer = new ZentinelleTracer({
        apiKey: 'sk_agent_test_key_123',
      });

      const result = await tracer.trace('operation', async () => {
        return 42;
      });

      expect(result).toBe(42);
    });

    it('should emit trace_start and trace_end events', async () => {
      const tracer = new ZentinelleTracer({
        apiKey: 'sk_agent_test_key_123',
      });

      await tracer.trace('wrapped-op', async () => 'done');

      const startCalls = mockEmit.mock.calls.filter(
        (c: any[]) => c[0] === 'trace_start'
      );
      const endCalls = mockEmit.mock.calls.filter(
        (c: any[]) => c[0] === 'trace_end'
      );

      expect(startCalls.length).toBe(1);
      expect(endCalls.length).toBe(1);
    });

    it('should record error and re-throw on failure', async () => {
      const tracer = new ZentinelleTracer({
        apiKey: 'sk_agent_test_key_123',
      });

      const error = new Error('operation failed');
      await expect(
        tracer.trace('failing-op', async () => {
          throw error;
        })
      ).rejects.toThrow('operation failed');

      // trace_end should still be emitted
      const endCalls = mockEmit.mock.calls.filter(
        (c: any[]) => c[0] === 'trace_end'
      );
      expect(endCalls.length).toBe(1);
    });

    it('should pass trace instance to the wrapped function', async () => {
      const tracer = new ZentinelleTracer({
        apiKey: 'sk_agent_test_key_123',
      });

      await tracer.trace('with-span', async (trace) => {
        trace.setAttribute('key', 'value');
        const span = trace.startSpan('inner-op');
        span.setAttribute('inner', true);
        span.end();
      });

      // span_end should have been emitted
      const spanEndCalls = mockEmit.mock.calls.filter(
        (c: any[]) => c[0] === 'span_end'
      );
      expect(spanEndCalls.length).toBe(1);
      expect(spanEndCalls[0][1]).toEqual(
        expect.objectContaining({
          name: 'inner-op',
          attributes: { inner: true },
        })
      );
    });
  });

  describe('shutdown', () => {
    it('should end all active traces', async () => {
      const tracer = new ZentinelleTracer({
        apiKey: 'sk_agent_test_key_123',
      });

      const trace1 = tracer.startTrace('trace-1');
      const trace2 = tracer.startTrace('trace-2');
      mockEmit.mockClear();

      await tracer.shutdown();

      // Both traces should have emitted trace_end
      const endCalls = mockEmit.mock.calls.filter(
        (c: any[]) => c[0] === 'trace_end'
      );
      expect(endCalls.length).toBe(2);

      // Active traces should be cleared
      expect(tracer.getTrace(trace1.id)).toBeUndefined();
      expect(tracer.getTrace(trace2.id)).toBeUndefined();
    });

    it('should call client shutdown', async () => {
      const tracer = new ZentinelleTracer({
        apiKey: 'sk_agent_test_key_123',
      });

      await tracer.shutdown();

      expect(mockShutdown).toHaveBeenCalled();
    });
  });
});

describe('Trace', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('setUserId', () => {
    it('should set userId and return this for chaining', () => {
      const tracer = new ZentinelleTracer({
        apiKey: 'sk_agent_test_key_123',
      });

      const trace = tracer.startTrace('test');
      const result = trace.setUserId('user-42');

      expect(result).toBe(trace);
    });
  });

  describe('setAttribute', () => {
    it('should set attribute and return this for chaining', () => {
      const tracer = new ZentinelleTracer({
        apiKey: 'sk_agent_test_key_123',
      });

      const trace = tracer.startTrace('test');
      const result = trace.setAttribute('model', 'gpt-4o');

      expect(result).toBe(trace);
    });
  });

  describe('addEvent', () => {
    it('should add event and return this for chaining', () => {
      const tracer = new ZentinelleTracer({
        apiKey: 'sk_agent_test_key_123',
      });

      const trace = tracer.startTrace('test');
      const result = trace.addEvent('checkpoint', { step: 1 });

      expect(result).toBe(trace);
    });
  });

  describe('recordError', () => {
    it('should record error as event and return this for chaining', () => {
      const tracer = new ZentinelleTracer({
        apiKey: 'sk_agent_test_key_123',
      });

      const trace = tracer.startTrace('test');
      const error = new Error('something went wrong');
      const result = trace.recordError(error);

      expect(result).toBe(trace);
    });
  });

  describe('end', () => {
    it('should only end once (idempotent)', () => {
      const tracer = new ZentinelleTracer({
        apiKey: 'sk_agent_test_key_123',
      });

      const trace = tracer.startTrace('test');
      mockEmit.mockClear();

      trace.end();
      trace.end();
      trace.end();

      const endCalls = mockEmit.mock.calls.filter(
        (c: any[]) => c[0] === 'trace_end'
      );
      expect(endCalls.length).toBe(1);
    });

    it('should include span and event counts in trace_end', () => {
      const tracer = new ZentinelleTracer({
        apiKey: 'sk_agent_test_key_123',
      });

      const trace = tracer.startTrace('test');
      trace.addEvent('event1');
      trace.addEvent('event2');
      trace.startSpan('span1').end();
      trace.startSpan('span2').end();
      trace.startSpan('span3').end();
      mockEmit.mockClear();

      trace.end();

      expect(mockEmit).toHaveBeenCalledWith(
        'trace_end',
        expect.objectContaining({
          span_count: 3,
          event_count: 2,
        }),
        expect.anything()
      );
    });
  });

  describe('getSummary', () => {
    it('should return trace summary before ending', () => {
      const tracer = new ZentinelleTracer({
        apiKey: 'sk_agent_test_key_123',
      });

      const trace = tracer.startTrace('summarize-test', { key: 'value' });
      const summary = trace.getSummary();

      expect(summary.id).toBe(trace.id);
      expect(summary.name).toBe('summarize-test');
      expect(summary.startTime).toBeDefined();
      // endTime is undefined (not yet ended), durationMs is null
      expect(summary.endTime).toBeUndefined();
      expect(summary.durationMs).toBeNull();
      expect(summary.attributes).toEqual({ key: 'value' });
    });

    it('should include duration after ending', () => {
      const tracer = new ZentinelleTracer({
        apiKey: 'sk_agent_test_key_123',
      });

      const trace = tracer.startTrace('timed-test');
      trace.end();
      const summary = trace.getSummary();

      expect(summary.endTime).toBeDefined();
      expect(summary.durationMs).toBeGreaterThanOrEqual(0);
    });

    it('should report span and event counts', () => {
      const tracer = new ZentinelleTracer({
        apiKey: 'sk_agent_test_key_123',
      });

      const trace = tracer.startTrace('counts-test');
      trace.addEvent('ev1');
      trace.addEvent('ev2');
      trace.startSpan('sp1').end();

      const summary = trace.getSummary();
      expect(summary.spanCount).toBe(1);
      expect(summary.eventCount).toBe(2);
    });
  });

  describe('startSpan', () => {
    it('should create a span and emit span_end on end', () => {
      const tracer = new ZentinelleTracer({
        apiKey: 'sk_agent_test_key_123',
      });

      const trace = tracer.startTrace('span-test');
      mockEmit.mockClear();

      const span = trace.startSpan('model-call', { model: 'gpt-4o' });
      span.end();

      expect(mockEmit).toHaveBeenCalledWith(
        'span_end',
        expect.objectContaining({
          trace_id: trace.id,
          name: 'model-call',
          duration_ms: expect.any(Number),
          attributes: { model: 'gpt-4o' },
        }),
        expect.objectContaining({ category: 'telemetry' })
      );
    });

    it('should support span setAttribute', () => {
      const tracer = new ZentinelleTracer({
        apiKey: 'sk_agent_test_key_123',
      });

      const trace = tracer.startTrace('attr-test');
      mockEmit.mockClear();

      const span = trace.startSpan('op');
      span.setAttribute('key1', 'value1');
      span.setAttribute('key2', 42);
      span.end();

      expect(mockEmit).toHaveBeenCalledWith(
        'span_end',
        expect.objectContaining({
          attributes: { key1: 'value1', key2: 42 },
        }),
        expect.anything()
      );
    });

    it('should support span addEvent', () => {
      const tracer = new ZentinelleTracer({
        apiKey: 'sk_agent_test_key_123',
      });

      const trace = tracer.startTrace('event-test');
      mockEmit.mockClear();

      const span = trace.startSpan('op');
      span.addEvent('checkpoint', { step: 1 });
      span.addEvent('checkpoint', { step: 2 });
      span.end();

      expect(mockEmit).toHaveBeenCalledWith(
        'span_end',
        expect.objectContaining({
          event_count: 2,
        }),
        expect.anything()
      );
    });

    it('should support span recordError', () => {
      const tracer = new ZentinelleTracer({
        apiKey: 'sk_agent_test_key_123',
      });

      const trace = tracer.startTrace('error-test');
      mockEmit.mockClear();

      const span = trace.startSpan('failing-op');
      span.recordError(new TypeError('invalid input'));
      span.end();

      expect(mockEmit).toHaveBeenCalledWith(
        'span_end',
        expect.objectContaining({
          event_count: 1,
        }),
        expect.anything()
      );
    });

    it('should be idempotent when ending a span', () => {
      const tracer = new ZentinelleTracer({
        apiKey: 'sk_agent_test_key_123',
      });

      const trace = tracer.startTrace('idempotent-test');
      mockEmit.mockClear();

      const span = trace.startSpan('op');
      span.end();
      span.end();
      span.end();

      const spanEndCalls = mockEmit.mock.calls.filter(
        (c: any[]) => c[0] === 'span_end'
      );
      expect(spanEndCalls.length).toBe(1);
    });

    it('should support chaining on setAttribute and addEvent', () => {
      const tracer = new ZentinelleTracer({
        apiKey: 'sk_agent_test_key_123',
      });

      const trace = tracer.startTrace('chaining-test');
      const span = trace.startSpan('op');

      const result1 = span.setAttribute('key', 'val');
      const result2 = span.addEvent('ev');
      const result3 = span.recordError(new Error('err'));

      expect(result1).toBe(span);
      expect(result2).toBe(span);
      expect(result3).toBe(span);
    });
  });
});
