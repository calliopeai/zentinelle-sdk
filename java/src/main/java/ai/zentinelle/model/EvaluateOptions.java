package ai.zentinelle.model;

import java.util.Map;

/**
 * Options for policy evaluation.
 */
public class EvaluateOptions {

    private final String userId;
    private final Map<String, Object> context;

    private EvaluateOptions(Builder builder) {
        this.userId = builder.userId;
        this.context = builder.context != null ? builder.context : Map.of();
    }

    public String getUserId() { return userId; }
    public Map<String, Object> getContext() { return context; }

    public static Builder builder() { return new Builder(); }

    public static class Builder {
        private String userId;
        private Map<String, Object> context;

        public Builder userId(String userId) { this.userId = userId; return this; }
        public Builder context(Map<String, Object> context) { this.context = context; return this; }

        public EvaluateOptions build() { return new EvaluateOptions(this); }
    }
}
