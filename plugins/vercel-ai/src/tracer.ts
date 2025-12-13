/**
 * Tracing for Vercel AI SDK with Zentinelle.
 */

import { ZentinelleClient } from 'zentinelle';

interface TraceEvent {
  type: string;
  timestamp: number;
  data: Record<string, unknown>;
}

interface Span {
  id: string;
  name: string;
  startTime: number;
  endTime?: number;
  events: TraceEvent[];
  attributes: Record<string, unknown>;
}

/**
 * Tracer for capturing AI SDK execution traces.
 *
 * Captures:
 * - Model requests and responses
 * - Tool invocations
 * - Streaming events
 * - Errors and retries
 *
 * @example
 * ```typescript
 * import { ZentinelleTracer } from 'zentinelle-ai';
 *
 * const tracer = new ZentinelleTracer({
 *   apiKey: 'sk_agent_...',
 *   agentType: 'vercel-ai',
 * });
 *
 * // Start a trace
 * const trace = tracer.startTrace('chat-completion');
 *
 * // Add spans for operations
 * const span = trace.startSpan('model-request');
 * span.setAttribute('model', 'gpt-4o');
 *
 * // ... perform operation ...
 *
 * span.end();
 * trace.end();
 * ```
 */
export class ZentinelleTracer {
  private client: ZentinelleClient;
  private activeTraces: Map<string, Trace> = new Map();

  constructor(options: {
    apiKey: string;
    agentType?: string;
    endpoint?: string;
  }) {
    this.client = new ZentinelleClient({
      apiKey: options.apiKey,
      agentType: options.agentType ?? 'vercel-ai',
      endpoint: options.endpoint,
    });
  }

  /**
   * Start a new trace.
   */
  startTrace(name: string, attributes?: Record<string, unknown>): Trace {
    const trace = new Trace(this.client, name, attributes);
    this.activeTraces.set(trace.id, trace);
    return trace;
  }

  /**
   * Get an active trace by ID.
   */
  getTrace(id: string): Trace | undefined {
    return this.activeTraces.get(id);
  }

  /**
   * End a trace and remove from active.
   */
  endTrace(id: string): void {
    const trace = this.activeTraces.get(id);
    if (trace) {
      trace.end();
      this.activeTraces.delete(id);
    }
  }

  /**
   * Wrap an async function with automatic tracing.
   */
  trace<T>(
    name: string,
    fn: (span: Trace) => Promise<T>,
    attributes?: Record<string, unknown>
  ): Promise<T> {
    const trace = this.startTrace(name, attributes);

    return fn(trace)
      .then((result) => {
        trace.end();
        return result;
      })
      .catch((error) => {
        trace.recordError(error as Error);
        trace.end();
        throw error;
      });
  }

  /**
   * Shutdown and flush.
   */
  async shutdown(): Promise<void> {
    // End all active traces
    for (const trace of this.activeTraces.values()) {
      trace.end();
    }
    this.activeTraces.clear();

    return this.client.shutdown();
  }
}

class Trace {
  readonly id: string;
  private client: ZentinelleClient;
  private name: string;
  private startTime: number;
  private endTime?: number;
  private spans: Span[] = [];
  private attributes: Record<string, unknown>;
  private events: TraceEvent[] = [];
  private userId?: string;

  constructor(
    client: ZentinelleClient,
    name: string,
    attributes?: Record<string, unknown>
  ) {
    this.id = generateId();
    this.client = client;
    this.name = name;
    this.startTime = Date.now();
    this.attributes = attributes ?? {};

    this.client.emit('trace_start', {
      trace_id: this.id,
      name: this.name,
      attributes: this.attributes,
    }, { category: 'telemetry', userId: this.userId });
  }

  /**
   * Start a new span within this trace.
   */
  startSpan(name: string, attributes?: Record<string, unknown>): SpanBuilder {
    const span: Span = {
      id: generateId(),
      name,
      startTime: Date.now(),
      events: [],
      attributes: attributes ?? {},
    };
    this.spans.push(span);
    return new SpanBuilder(span, this.client, this.id, this.userId);
  }

  /**
   * Set the user ID for this trace.
   */
  setUserId(userId: string): this {
    this.userId = userId;
    return this;
  }

  /**
   * Set an attribute on the trace.
   */
  setAttribute(key: string, value: unknown): this {
    this.attributes[key] = value;
    return this;
  }

  /**
   * Add an event to the trace.
   */
  addEvent(type: string, data: Record<string, unknown> = {}): this {
    this.events.push({
      type,
      timestamp: Date.now(),
      data,
    });
    return this;
  }

  /**
   * Record an error on the trace.
   */
  recordError(error: Error): this {
    this.addEvent('error', {
      error_type: error.name,
      error_message: error.message,
      stack: error.stack?.slice(0, 1000),
    });
    return this;
  }

  /**
   * End the trace.
   */
  end(): void {
    if (this.endTime) return;

    this.endTime = Date.now();
    const durationMs = this.endTime - this.startTime;

    this.client.emit('trace_end', {
      trace_id: this.id,
      name: this.name,
      duration_ms: durationMs,
      span_count: this.spans.length,
      event_count: this.events.length,
      attributes: this.attributes,
    }, { category: 'telemetry', userId: this.userId });
  }

  /**
   * Get trace summary.
   */
  getSummary(): Record<string, unknown> {
    return {
      id: this.id,
      name: this.name,
      startTime: this.startTime,
      endTime: this.endTime,
      durationMs: this.endTime ? this.endTime - this.startTime : null,
      spanCount: this.spans.length,
      eventCount: this.events.length,
      attributes: this.attributes,
    };
  }
}

class SpanBuilder {
  private span: Span;
  private client: ZentinelleClient;
  private traceId: string;
  private userId?: string;

  constructor(
    span: Span,
    client: ZentinelleClient,
    traceId: string,
    userId?: string
  ) {
    this.span = span;
    this.client = client;
    this.traceId = traceId;
    this.userId = userId;
  }

  /**
   * Set an attribute on the span.
   */
  setAttribute(key: string, value: unknown): this {
    this.span.attributes[key] = value;
    return this;
  }

  /**
   * Add an event to the span.
   */
  addEvent(type: string, data: Record<string, unknown> = {}): this {
    this.span.events.push({
      type,
      timestamp: Date.now(),
      data,
    });
    return this;
  }

  /**
   * Record an error on the span.
   */
  recordError(error: Error): this {
    this.addEvent('error', {
      error_type: error.name,
      error_message: error.message,
    });
    return this;
  }

  /**
   * End the span.
   */
  end(): void {
    if (this.span.endTime) return;

    this.span.endTime = Date.now();
    const durationMs = this.span.endTime - this.span.startTime;

    this.client.emit('span_end', {
      trace_id: this.traceId,
      span_id: this.span.id,
      name: this.span.name,
      duration_ms: durationMs,
      attributes: this.span.attributes,
      event_count: this.span.events.length,
    }, { category: 'telemetry', userId: this.userId });
  }
}

function generateId(): string {
  return Math.random().toString(36).substring(2, 15) +
    Math.random().toString(36).substring(2, 15);
}
