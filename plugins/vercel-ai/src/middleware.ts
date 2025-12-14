/**
 * Middleware for Next.js API routes with Zentinelle governance.
 */

import { ZentinelleClient } from 'zentinelle';
import { PolicyViolationError } from './errors';

export interface MiddlewareOptions {
  apiKey: string;
  agentType?: string;
  endpoint?: string;
  /** Extract user ID from request */
  getUserId?: (req: Request) => string | undefined;
  /** Extract action context from request */
  getContext?: (req: Request) => Record<string, unknown>;
  /** Action name for policy evaluation */
  action?: string;
  /** Allow request if Zentinelle is unavailable */
  failOpen?: boolean;
}

export interface MiddlewareResult {
  allowed: boolean;
  reason?: string;
  warnings: string[];
  userId?: string;
}

/**
 * Zentinelle middleware for Next.js API routes.
 *
 * @example
 * ```typescript
 * // app/api/chat/route.ts
 * import { streamText } from 'ai';
 * import { openai } from '@ai-sdk/openai';
 * import { ZentinelleMiddleware } from 'zentinelle-ai';
 *
 * const middleware = new ZentinelleMiddleware({
 *   apiKey: process.env.ZENTINELLE_API_KEY!,
 *   agentType: 'nextjs-chat',
 *   getUserId: (req) => req.headers.get('x-user-id') ?? undefined,
 * });
 *
 * export async function POST(req: Request) {
 *   // Check governance
 *   const check = await middleware.evaluate(req);
 *   if (!check.allowed) {
 *     return new Response(JSON.stringify({ error: check.reason }), {
 *       status: 403,
 *       headers: { 'Content-Type': 'application/json' },
 *     });
 *   }
 *
 *   // Process request
 *   const { messages } = await req.json();
 *   const result = await streamText({
 *     model: openai('gpt-4o'),
 *     messages,
 *   });
 *
 *   // Track completion
 *   middleware.trackCompletion(result, check.userId);
 *
 *   return result.toDataStreamResponse();
 * }
 * ```
 */
/**
 * Model name patterns for provider detection.
 */
const PROVIDER_PATTERNS: Record<string, string[]> = {
  openai: ['gpt-', 'text-davinci', 'text-curie', 'text-babbage', 'text-ada', 'o1-', 'chatgpt'],
  anthropic: ['claude-', 'anthropic'],
  google: ['gemini-', 'palm-', 'bison', 'gecko'],
  cohere: ['command', 'cohere'],
  mistral: ['mistral', 'mixtral'],
  meta: ['llama', 'codellama'],
  together: ['togethercomputer/', 'together/'],
  groq: ['groq/'],
  fireworks: ['fireworks/', 'accounts/fireworks'],
  huggingface: ['huggingface/', 'hf/'],
  deepseek: ['deepseek'],
  ai21: ['j2-', 'jamba'],
  perplexity: ['pplx-', 'sonar'],
  aws_bedrock: ['amazon.', 'bedrock/'],
  azure_openai: ['azure/'],
};

/**
 * Detect AI provider from model name.
 */
function detectProvider(model?: string): string {
  if (!model) return 'unknown';
  const modelLower = model.toLowerCase();

  for (const [provider, patterns] of Object.entries(PROVIDER_PATTERNS)) {
    for (const pattern of patterns) {
      if (modelLower.includes(pattern)) {
        return provider;
      }
    }
  }

  return 'unknown';
}

export class ZentinelleMiddleware {
  private client: ZentinelleClient;
  private options: MiddlewareOptions;

  constructor(options: MiddlewareOptions) {
    this.options = options;
    this.client = new ZentinelleClient({
      apiKey: options.apiKey,
      agentType: options.agentType ?? 'nextjs',
      endpoint: options.endpoint,
      failOpen: options.failOpen ?? false,
    });
  }

  /**
   * Evaluate request against policies.
   */
  async evaluate(req: Request): Promise<MiddlewareResult> {
    const userId = this.options.getUserId?.(req);
    const context = this.options.getContext?.(req) ?? {};

    // Add request metadata to context
    const fullContext = {
      ...context,
      method: req.method,
      path: new URL(req.url).pathname,
      userAgent: req.headers.get('user-agent')?.slice(0, 100),
    };

    try {
      const result = await this.client.evaluate(
        this.options.action ?? 'api_request',
        {
          userId,
          context: fullContext,
        }
      );

      return {
        allowed: result.allowed,
        reason: result.reason,
        warnings: result.warnings,
        userId,
      };
    } catch (error) {
      if (this.options.failOpen) {
        console.warn('[Zentinelle] Policy evaluation failed, failing open:', error);
        return {
          allowed: true,
          warnings: ['Policy evaluation failed, allowing request (fail-open mode)'],
          userId,
        };
      }
      throw error;
    }
  }

  /**
   * Create a wrapper that returns a Response on policy violation.
   */
  async guard(req: Request): Promise<Response | null> {
    const result = await this.evaluate(req);

    if (!result.allowed) {
      return new Response(
        JSON.stringify({
          error: 'Request blocked by policy',
          reason: result.reason,
        }),
        {
          status: 403,
          headers: { 'Content-Type': 'application/json' },
        }
      );
    }

    // Log warnings
    for (const warning of result.warnings) {
      console.warn(`[Zentinelle] ${warning}`);
    }

    return null; // Allow request to proceed
  }

  /**
   * Track a completion after it's finished.
   *
   * @param result - The completion result with usage stats
   * @param userId - User ID for tracking
   * @param model - Model name (used for provider detection if not specified)
   * @param provider - Explicit provider override (optional)
   */
  trackCompletion(
    result: { usage?: { promptTokens: number; completionTokens: number } },
    userId?: string,
    model?: string,
    provider?: string
  ): void {
    if (result.usage) {
      this.client.emitModelRequest({
        provider: provider ?? detectProvider(model),
        model: model ?? 'unknown',
        inputTokens: result.usage.promptTokens,
        outputTokens: result.usage.completionTokens,
        userId,
      });
    }
  }

  /**
   * Emit a custom event.
   */
  emit(
    eventType: string,
    payload: Record<string, unknown>,
    options?: { userId?: string; category?: 'telemetry' | 'audit' | 'alert' }
  ): void {
    this.client.emit(eventType, payload, {
      category: options?.category ?? 'telemetry',
      userId: options?.userId,
    });
  }

  /**
   * Get the underlying client for advanced usage.
   */
  getClient(): ZentinelleClient {
    return this.client;
  }

  /**
   * Shutdown and flush events.
   */
  async shutdown(): Promise<void> {
    return this.client.shutdown();
  }
}

/**
 * Higher-order function to wrap an API route handler with governance.
 *
 * @example
 * ```typescript
 * import { withGovernance } from 'zentinelle-ai';
 *
 * const governance = withGovernance({
 *   apiKey: process.env.ZENTINELLE_API_KEY!,
 *   getUserId: (req) => req.headers.get('x-user-id'),
 * });
 *
 * export const POST = governance(async (req, { userId }) => {
 *   // Your handler code here
 *   return new Response('OK');
 * });
 * ```
 */
export function withGovernance(options: MiddlewareOptions) {
  const middleware = new ZentinelleMiddleware(options);

  return function <T extends (req: Request, context: { userId?: string }) => Promise<Response>>(
    handler: T
  ) {
    return async (req: Request): Promise<Response> => {
      const blocked = await middleware.guard(req);
      if (blocked) return blocked;

      const result = await middleware.evaluate(req);
      return handler(req, { userId: result.userId });
    };
  };
}
