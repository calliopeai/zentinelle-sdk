package ai.zentinelle.model;

import java.time.Instant;
import java.util.List;
import java.util.Map;

/**
 * Result of a config fetch.
 */
public class ConfigResult {

    private final String agentId;
    private final Map<String, Object> config;
    private final List<PolicyConfig> policies;
    private final Instant updatedAt;

    private ConfigResult(Builder builder) {
        this.agentId = builder.agentId;
        this.config = builder.config != null ? builder.config : Map.of();
        this.policies = builder.policies != null ? builder.policies : List.of();
        this.updatedAt = builder.updatedAt != null ? builder.updatedAt : Instant.now();
    }

    public String getAgentId() { return agentId; }
    public Map<String, Object> getConfig() { return config; }
    public List<PolicyConfig> getPolicies() { return policies; }
    public Instant getUpdatedAt() { return updatedAt; }

    public static Builder builder() { return new Builder(); }

    public static class Builder {
        private String agentId;
        private Map<String, Object> config;
        private List<PolicyConfig> policies;
        private Instant updatedAt;

        public Builder agentId(String agentId) { this.agentId = agentId; return this; }
        public Builder config(Map<String, Object> config) { this.config = config; return this; }
        public Builder policies(List<PolicyConfig> policies) { this.policies = policies; return this; }
        public Builder updatedAt(Instant updatedAt) { this.updatedAt = updatedAt; return this; }

        public ConfigResult build() { return new ConfigResult(this); }
    }
}
