package ai.zentinelle.model;

import java.util.List;
import java.util.Map;

/**
 * Result of agent registration.
 */
public class RegisterResult {

    private final String agentId;
    private final String apiKey;
    private final Map<String, Object> config;
    private final List<PolicyConfig> policies;

    private RegisterResult(Builder builder) {
        this.agentId = builder.agentId;
        this.apiKey = builder.apiKey;
        this.config = builder.config != null ? builder.config : Map.of();
        this.policies = builder.policies != null ? builder.policies : List.of();
    }

    public String getAgentId() { return agentId; }
    public String getApiKey() { return apiKey; }
    public Map<String, Object> getConfig() { return config; }
    public List<PolicyConfig> getPolicies() { return policies; }

    public static Builder builder() { return new Builder(); }

    public static class Builder {
        private String agentId;
        private String apiKey;
        private Map<String, Object> config;
        private List<PolicyConfig> policies;

        public Builder agentId(String agentId) { this.agentId = agentId; return this; }
        public Builder apiKey(String apiKey) { this.apiKey = apiKey; return this; }
        public Builder config(Map<String, Object> config) { this.config = config; return this; }
        public Builder policies(List<PolicyConfig> policies) { this.policies = policies; return this; }

        public RegisterResult build() { return new RegisterResult(this); }
    }
}
