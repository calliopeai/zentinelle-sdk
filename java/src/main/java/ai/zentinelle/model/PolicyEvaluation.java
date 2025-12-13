package ai.zentinelle.model;

/**
 * Result of a single policy evaluation.
 */
public class PolicyEvaluation {

    private final String name;
    private final String type;
    private final boolean passed;
    private final String message;

    private PolicyEvaluation(Builder builder) {
        this.name = builder.name;
        this.type = builder.type;
        this.passed = builder.passed;
        this.message = builder.message;
    }

    public String getName() { return name; }
    public String getType() { return type; }
    public boolean isPassed() { return passed; }
    public String getMessage() { return message; }

    public static Builder builder() { return new Builder(); }

    public static class Builder {
        private String name;
        private String type;
        private boolean passed = true;
        private String message;

        public Builder name(String name) { this.name = name; return this; }
        public Builder type(String type) { this.type = type; return this; }
        public Builder passed(boolean passed) { this.passed = passed; return this; }
        public Builder message(String message) { this.message = message; return this; }

        public PolicyEvaluation build() { return new PolicyEvaluation(this); }
    }
}
