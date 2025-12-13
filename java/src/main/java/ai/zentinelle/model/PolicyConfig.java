package ai.zentinelle.model;

import java.util.Map;

/**
 * Policy configuration.
 */
public class PolicyConfig {

    private final String id;
    private final String name;
    private final String type;
    private final String enforcement;
    private final Map<String, Object> config;
    private final int priority;

    private PolicyConfig(Builder builder) {
        this.id = builder.id;
        this.name = builder.name;
        this.type = builder.type;
        this.enforcement = builder.enforcement;
        this.config = builder.config != null ? builder.config : Map.of();
        this.priority = builder.priority;
    }

    public String getId() { return id; }
    public String getName() { return name; }
    public String getType() { return type; }
    public String getEnforcement() { return enforcement; }
    public Map<String, Object> getConfig() { return config; }
    public int getPriority() { return priority; }

    /**
     * Returns true if the policy is actively enforced.
     */
    public boolean isEnforced() {
        return "enforce".equals(enforcement);
    }

    public static Builder builder() { return new Builder(); }

    public static class Builder {
        private String id;
        private String name;
        private String type;
        private String enforcement;
        private Map<String, Object> config;
        private int priority = 100;

        public Builder id(String id) { this.id = id; return this; }
        public Builder name(String name) { this.name = name; return this; }
        public Builder type(String type) { this.type = type; return this; }
        public Builder enforcement(String enforcement) { this.enforcement = enforcement; return this; }
        public Builder config(Map<String, Object> config) { this.config = config; return this; }
        public Builder priority(int priority) { this.priority = priority; return this; }

        public PolicyConfig build() { return new PolicyConfig(this); }
    }
}
