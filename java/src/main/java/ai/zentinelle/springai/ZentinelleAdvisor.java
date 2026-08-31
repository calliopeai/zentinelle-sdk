package ai.zentinelle.springai;

import ai.zentinelle.ZentinelleClient;
import ai.zentinelle.model.EvaluateOptions;
import ai.zentinelle.model.EvaluateResult;
import ai.zentinelle.model.ModelUsage;

import org.springframework.ai.chat.client.ChatClientRequest;
import org.springframework.ai.chat.client.ChatClientResponse;
import org.springframework.ai.chat.client.advisor.api.CallAdvisor;
import org.springframework.ai.chat.client.advisor.api.CallAdvisorChain;
import org.springframework.ai.chat.metadata.Usage;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.logging.Level;
import java.util.logging.Logger;

/**
 * Zentinelle governance for Spring AI, as a {@link CallAdvisor}.
 *
 * <p>Spring AI's advisor chain is middleware: an advisor receives the request
 * and the rest of the chain, and decides whether to call it. So enforcement is
 * simply not calling {@code chain.nextCall(request)} — the model is never
 * reached, rather than reached and then discarded.
 *
 * <p>Register with {@code ChatClient.builder(model).defaultAdvisors(new
 * ZentinelleAdvisor(client)).build()}, or per-request with
 * {@code .advisors(...)}.
 *
 * <p>Only the blocking {@code CallAdvisor} half is implemented. Spring AI's
 * streaming half is {@code StreamAdvisor}, which hands back a reactive
 * publisher; a policy decision made on the first chunk of a stream is a
 * different design, not the same one with a Flux around it, and shipping a
 * half-considered version would give a deployment the impression that its
 * streaming calls were governed. Streaming calls are unaffected by this
 * advisor and should be routed through the Zentinelle gateway instead.
 *
 * <p>agent_type: {@code spring_ai}
 */
public class ZentinelleAdvisor implements CallAdvisor {

    private static final Logger LOGGER = Logger.getLogger(ZentinelleAdvisor.class.getName());

    /** Prompts are truncated: a long conversation should not be posted whole on every check. */
    private static final int CONTENT_LIMIT = 4000;

    public static final String AGENT_TYPE = "spring_ai";

    private final ZentinelleClient client;
    private final String userId;
    private final boolean evaluateRequests;
    private final boolean trackTokenUsage;
    private final boolean failOpen;
    private final int order;

    public ZentinelleAdvisor(ZentinelleClient client) {
        this(client, null, true, true, false, 0);
    }

    public ZentinelleAdvisor(ZentinelleClient client, String userId) {
        this(client, userId, true, true, false, 0);
    }

    public ZentinelleAdvisor(
            ZentinelleClient client,
            String userId,
            boolean evaluateRequests,
            boolean trackTokenUsage,
            boolean failOpen,
            int order) {
        if (client == null) {
            throw new IllegalArgumentException("client is required");
        }
        this.client = client;
        this.userId = userId;
        this.evaluateRequests = evaluateRequests;
        this.trackTokenUsage = trackTokenUsage;
        this.failOpen = failOpen;
        this.order = order;
    }

    @Override
    public String getName() {
        return "zentinelle";
    }

    @Override
    public int getOrder() {
        // Low order runs early. A governance advisor that ran after a
        // memory or RAG advisor would be evaluating a prompt those had
        // already rewritten, which is not the prompt the caller sent.
        return this.order;
    }

    @Override
    public ChatClientResponse adviseCall(ChatClientRequest request, CallAdvisorChain chain) {
        if (this.evaluateRequests) {
            check(request);
        }

        ChatClientResponse response = chain.nextCall(request);

        if (this.trackTokenUsage) {
            track(response);
        }
        return response;
    }

    private void check(ChatClientRequest request) {
        Map<String, Object> context = new LinkedHashMap<>();
        context.put("direction", "input");
        context.put("harness", AGENT_TYPE);
        context.put("content", contentOf(request));

        EvaluateResult result;
        try {
            result = this.client.evaluate(
                    "model_request",
                    EvaluateOptions.builder().userId(this.userId).context(context).build());
        } catch (Exception exc) {
            if (this.failOpen) {
                LOGGER.log(Level.WARNING, "Zentinelle check failed, allowing", exc);
                return;
            }
            // No EvaluateResult exists on this path: the evaluation never
            // returned one. Null rather than a fabricated "denied" result, so
            // a caller inspecting getResult() can tell a policy denial from a
            // control-plane failure.
            throw new PolicyDeniedException(
                    "Zentinelle policy check failed and failOpen is off: " + exc.getMessage(),
                    null);
        }

        if (!result.isAllowed()) {
            String reason = result.getReason() != null ? result.getReason() : "no reason given";
            throw new PolicyDeniedException("Request refused by policy: " + reason, result);
        }
    }

    private String contentOf(ChatClientRequest request) {
        if (request == null || request.prompt() == null) {
            return "";
        }
        String contents = request.prompt().getContents();
        if (contents == null) {
            return "";
        }
        return contents.length() > CONTENT_LIMIT
                ? contents.substring(0, CONTENT_LIMIT)
                : contents;
    }

    private void track(ChatClientResponse response) {
        try {
            if (response == null
                    || response.chatResponse() == null
                    || response.chatResponse().getMetadata() == null) {
                return;
            }
            Usage usage = response.chatResponse().getMetadata().getUsage();
            if (usage == null) {
                return;
            }
            String model = response.chatResponse().getMetadata().getModel();
            this.client.trackUsage(ModelUsage.builder()
                    .provider("openai")
                    .model(model != null && !model.isEmpty() ? model : "unknown")
                    .inputTokens(orZero(usage.getPromptTokens()))
                    .outputTokens(orZero(usage.getCompletionTokens()))
                    .build());
        } catch (Exception exc) {
            // Telemetry is best-effort. A run must not fail because a usage
            // buffer refused an append.
            LOGGER.log(Level.WARNING, "Could not record model usage", exc);
        }
    }

    private static int orZero(Integer value) {
        return value == null ? 0 : value;
    }
}
