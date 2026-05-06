package ai.zentinelle;

import ai.zentinelle.model.ConfigResult;
import ai.zentinelle.model.HeartbeatResult;
import ai.zentinelle.model.RegisterOptions;
import ai.zentinelle.model.RegisterResult;
import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;
import okhttp3.mockwebserver.RecordedRequest;
import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

class ZentinelleClientTest {

    @Test
    void registerUsesBootstrapHeaderAndSwapsRuntimeKey() throws Exception {
        try (MockWebServer server = new MockWebServer()) {
            server.enqueue(jsonResponse(201, """
                {
                  "agent_id": "agent-runtime",
                  "api_key": "sk_agent_runtime_key",
                  "config": {"heartbeat_interval_seconds": 60},
                  "policies": []
                }
                """));
            server.enqueue(jsonResponse(200, """
                {
                  "allowed": true,
                  "reason": "ok",
                  "policies_evaluated": [],
                  "warnings": [],
                  "context": {}
                }
                """));
            server.start();

            try (ZentinelleClient client = ZentinelleClient.builder()
                .apiKey("bt_tenant_signature")
                .agentType("java-agent")
                .endpoint(server.url("/").toString())
                .failOpen(false)
                .build()) {

                RegisterResult result = client.register(RegisterOptions.builder()
                    .name("Example Agent")
                    .build());

                assertEquals("agent-runtime", result.getAgentId());
                assertEquals("sk_agent_runtime_key", result.getApiKey());

                client.evaluate("tool_call", ai.zentinelle.model.EvaluateOptions.builder()
                    .userId("user-1")
                    .context(Map.of("tool", "web_search"))
                    .build());
            }

            RecordedRequest registerRequest = server.takeRequest();
            assertEquals("/api/zentinelle/v1/register", registerRequest.getPath());
            assertEquals("bt_tenant_signature", registerRequest.getHeader("X-Zentinelle-Bootstrap"));
            assertNull(registerRequest.getHeader("X-Zentinelle-Key"));

            RecordedRequest evaluateRequest = server.takeRequest();
            assertEquals("/api/zentinelle/v1/evaluate", evaluateRequest.getPath());
            assertEquals("sk_agent_runtime_key", evaluateRequest.getHeader("X-Zentinelle-Key"));
        }
    }

    @Test
    void configSecretsAndHeartbeatUseCanonicalPaths() throws Exception {
        try (MockWebServer server = new MockWebServer()) {
            server.enqueue(jsonResponse(201, """
                {
                  "agent_id": "agent-123",
                  "api_key": "sk_agent_runtime_key",
                  "config": {"mode": "cached"},
                  "policies": []
                }
                """));
            server.enqueue(jsonResponse(200, """
                {
                  "agent_id": "agent-123",
                  "config": {"mode": "strict"},
                  "policies": [
                    {
                      "id": "policy-1",
                      "name": "No PII",
                      "type": "pii_filter",
                      "enforcement": "enforce",
                      "config": {"redact": true}
                    }
                  ],
                  "updated_at": "2026-04-10T00:00:00Z"
                }
                """));
            server.enqueue(jsonResponse(200, """
                {
                  "secrets": {"OPENAI_API_KEY": "secret-value"}
                }
                """));
            server.enqueue(jsonResponse(202, """
                {
                  "acknowledged": true,
                  "config_changed": true,
                  "next_heartbeat_seconds": 30
                }
                """));
            server.start();

            try (ZentinelleClient client = ZentinelleClient.builder()
                .apiKey("bt_tenant_signature")
                .agentType("java-agent")
                .endpoint(server.url("/").toString())
                .failOpen(false)
                .build()) {

                client.register(RegisterOptions.builder().build());

                ConfigResult config = client.getConfig(true);
                assertEquals("agent-123", config.getAgentId());
                assertEquals("strict", config.getConfig().get("mode"));

                Map<String, String> secrets = client.getSecrets();
                assertEquals("secret-value", secrets.get("OPENAI_API_KEY"));

                HeartbeatResult heartbeat = client.heartbeat("healthy", Map.of("queue_depth", 5));
                assertNotNull(heartbeat);
                assertTrue(heartbeat.isAcknowledged());
                assertTrue(heartbeat.isConfigChanged());
                assertEquals(30, heartbeat.getNextHeartbeatSeconds());
            }

            RecordedRequest registerRequest = server.takeRequest();
            assertEquals("/api/zentinelle/v1/register", registerRequest.getPath());

            RecordedRequest configRequest = server.takeRequest();
            assertEquals("/api/zentinelle/v1/config/agent-123", configRequest.getPath());
            assertEquals("sk_agent_runtime_key", configRequest.getHeader("X-Zentinelle-Key"));

            RecordedRequest secretsRequest = server.takeRequest();
            assertEquals("/api/zentinelle/v1/secrets/agent-123", secretsRequest.getPath());
            assertEquals("sk_agent_runtime_key", secretsRequest.getHeader("X-Zentinelle-Key"));

            RecordedRequest heartbeatRequest = server.takeRequest();
            assertEquals("/api/zentinelle/v1/heartbeat", heartbeatRequest.getPath());
            assertEquals("sk_agent_runtime_key", heartbeatRequest.getHeader("X-Zentinelle-Key"));
        }
    }

    private MockResponse jsonResponse(int statusCode, String body) {
        return new MockResponse()
            .setResponseCode(statusCode)
            .addHeader("Content-Type", "application/json")
            .setBody(body);
    }
}
