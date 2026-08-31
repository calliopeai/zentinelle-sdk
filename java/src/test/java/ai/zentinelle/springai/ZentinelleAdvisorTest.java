package ai.zentinelle.springai;

import ai.zentinelle.ZentinelleClient;

import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;
import org.junit.jupiter.api.Test;

import org.springframework.ai.chat.client.ChatClientRequest;
import org.springframework.ai.chat.client.ChatClientResponse;
import org.springframework.ai.chat.client.advisor.api.CallAdvisor;
import org.springframework.ai.chat.client.advisor.api.CallAdvisorChain;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.prompt.Prompt;

import java.time.Duration;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/**
 * The advisor is middleware: it decides whether to call the rest of the chain.
 * So the assertion that matters throughout is not what was thrown, but whether
 * {@code nextCall} was reached — a denial that still calls the chain has
 * governed nothing.
 *
 * <p>Zentinelle is a real client against a MockWebServer rather than a mock
 * object, so the request shape and the response parsing are exercised too.
 */
class ZentinelleAdvisorTest {

    /** Records whether the rest of the chain was reached. */
    private static final class RecordingChain implements CallAdvisorChain {
        int calls = 0;

        @Override
        public ChatClientResponse nextCall(ChatClientRequest request) {
            this.calls++;
            return ChatClientResponse.builder()
                .chatResponse(new ChatResponse(List.of()))
                .build();
        }

        @Override
        public List<CallAdvisor> getCallAdvisors() {
            return List.of();
        }
    }

    private static ChatClientRequest request(String text) {
        return ChatClientRequest.builder().prompt(new Prompt(text)).build();
    }

    private static MockResponse json(int code, String body) {
        return new MockResponse()
            .setResponseCode(code)
            .setHeader("Content-Type", "application/json")
            .setBody(body);
    }

    private static final String ALLOW = """
        {"allowed": true, "reason": null, "policies_evaluated": [],
         "warnings": [], "context": {}}
        """;

    private static final String DENY = """
        {"allowed": false, "reason": "contains a credential",
         "policies_evaluated": [], "warnings": [], "context": {}}
        """;

    private static ZentinelleClient clientFor(MockWebServer server, boolean failOpen) {
        return ZentinelleClient.builder()
            .apiKey("sk_agent_test")
            // An agentId is required before evaluate() will call out at all;
            // without it the client refuses locally and every case here would
            // fail for that reason rather than for the one under test.
            .agentId("agent-test")
            .agentType(ZentinelleAdvisor.AGENT_TYPE)
            .endpoint(server.url("/").toString())
            .failOpen(failOpen)
            // No retries and a short timeout. With the defaults the
            // control-plane-failure case retries with backoff and the suite
            // took eight minutes, nearly all of it waiting to fail. The
            // behaviour under test is the advisor's, not the client's retry
            // policy, which ZentinelleClientTest already covers.
            .maxRetries(0)
            .timeout(java.time.Duration.ofSeconds(2))
            .build();
    }

    @Test
    void aDeniedRequestNeverReachesTheModel() throws Exception {
        try (MockWebServer server = new MockWebServer()) {
            server.enqueue(json(200, DENY));
            server.start();

            try (ZentinelleClient client = clientFor(server, false)) {
                RecordingChain chain = new RecordingChain();

                PolicyDeniedException thrown = assertThrows(
                    PolicyDeniedException.class,
                    () -> new ZentinelleAdvisor(client).adviseCall(request("my key"), chain));

                assertTrue(thrown.getMessage().contains("contains a credential"));
                assertEquals(0, chain.calls, "the chain was called despite the refusal");
            }
        }
    }

    @Test
    void anAllowedRequestReachesTheModel() throws Exception {
        try (MockWebServer server = new MockWebServer()) {
            server.enqueue(json(200, ALLOW));
            server.start();

            try (ZentinelleClient client = clientFor(server, false)) {
                RecordingChain chain = new RecordingChain();

                ChatClientResponse response =
                    new ZentinelleAdvisor(client).adviseCall(request("hello"), chain);

                assertNotNull(response);
                assertEquals(1, chain.calls);
            }
        }
    }

    @Test
    void anUnreachableControlPlaneRefusesByDefault() throws Exception {
        try (MockWebServer server = new MockWebServer()) {
            server.enqueue(json(500, "{}"));
            server.start();

            try (ZentinelleClient client = clientFor(server, false)) {
                RecordingChain chain = new RecordingChain();

                assertThrows(
                    PolicyDeniedException.class,
                    () -> new ZentinelleAdvisor(client).adviseCall(request("hello"), chain));
                assertEquals(0, chain.calls);
            }
        }
    }

    @Test
    void evaluationCanBeTurnedOff() throws Exception {
        try (MockWebServer server = new MockWebServer()) {
            server.start();

            try (ZentinelleClient client = clientFor(server, false)) {
                RecordingChain chain = new RecordingChain();
                // No response is enqueued: if this called Zentinelle at all it
                // would hang or fail, so reaching the chain proves it did not.
                new ZentinelleAdvisor(client, null, false, false, false, 0)
                    .adviseCall(request("hello"), chain);

                assertEquals(1, chain.calls);
                assertEquals(0, server.getRequestCount());
            }
        }
    }

    @Test
    void theAdvisorIsNamedAndOrdered() throws Exception {
        try (MockWebServer server = new MockWebServer()) {
            server.start();
            try (ZentinelleClient client = clientFor(server, false)) {
                ZentinelleAdvisor advisor = new ZentinelleAdvisor(client);
                assertEquals("zentinelle", advisor.getName());
                // Runs early by default: a governance advisor placed after a
                // memory or RAG advisor would evaluate a prompt those had
                // already rewritten, not the one the caller sent.
                assertEquals(0, advisor.getOrder());
            }
        }
    }

    @Test
    void aMissingClientIsRejectedAtConstruction() {
        assertThrows(IllegalArgumentException.class, () -> new ZentinelleAdvisor(null));
    }

    @Test
    void anEmptyPromptDoesNotBlowUp() throws Exception {
        try (MockWebServer server = new MockWebServer()) {
            server.enqueue(json(200, ALLOW));
            server.start();

            try (ZentinelleClient client = clientFor(server, false)) {
                RecordingChain chain = new RecordingChain();
                new ZentinelleAdvisor(client).adviseCall(request(""), chain);
                assertEquals(1, chain.calls);
            }
        }
    }

    @Test
    void aResponseWithoutUsageIsNotAnError() throws Exception {
        try (MockWebServer server = new MockWebServer()) {
            server.enqueue(json(200, ALLOW));
            server.start();

            try (ZentinelleClient client = clientFor(server, false)) {
                // RecordingChain returns a ChatResponse with no metadata usage;
                // tracking must skip it rather than throw on the way out.
                ChatClientResponse response =
                    new ZentinelleAdvisor(client).adviseCall(request("hello"), new RecordingChain());
                assertNotNull(response);
            }
        }
    }

}
