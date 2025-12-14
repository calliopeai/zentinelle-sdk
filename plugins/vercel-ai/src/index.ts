/**
 * Zentinelle Vercel AI SDK Integration
 *
 * Provides governance capabilities for Vercel AI SDK agents:
 * - governedGenerateText: Text generation with policy enforcement
 * - governedStreamText: Streaming with governance
 * - governedTool: Wrap tools with policy checks
 * - ZentinelleMiddleware: Request/response middleware
 *
 * @example
 * ```typescript
 * import { openai } from '@ai-sdk/openai';
 * import { createGovernedAI } from 'zentinelle-ai';
 *
 * const governed = createGovernedAI({
 *   apiKey: 'sk_agent_...',
 *   agentType: 'vercel-ai',
 * });
 *
 * // Governed text generation
 * const { text } = await governed.generateText({
 *   model: openai('gpt-4o'),
 *   prompt: 'Hello!',
 *   userId: 'user123',
 * });
 *
 * // Governed tools
 * const calculator = governed.tool({
 *   name: 'calculator',
 *   description: 'Calculate math',
 *   parameters: z.object({ expression: z.string() }),
 *   execute: async ({ expression }) => calculateSafely(expression), // Use a safe math parser
 * });
 * ```
 */

export { createGovernedAI, type GovernedAIOptions } from './governed';
export { governedTool, type GovernedToolOptions } from './tool';
export { ZentinelleMiddleware, type MiddlewareOptions } from './middleware';
export { ZentinelleTracer } from './tracer';
export { PolicyViolationError } from './errors';
