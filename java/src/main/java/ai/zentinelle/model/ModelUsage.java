package ai.zentinelle.model;

/**
 * Model usage for cost tracking.
 */
public class ModelUsage {

    private final String provider;
    private final String model;
    private final int inputTokens;
    private final int outputTokens;
    private final double estimatedCost;

    private ModelUsage(Builder builder) {
        this.provider = builder.provider;
        this.model = builder.model;
        this.inputTokens = builder.inputTokens;
        this.outputTokens = builder.outputTokens;
        this.estimatedCost = builder.estimatedCost;
    }

    public String getProvider() { return provider; }
    public String getModel() { return model; }
    public int getInputTokens() { return inputTokens; }
    public int getOutputTokens() { return outputTokens; }
    public double getEstimatedCost() { return estimatedCost; }

    public int getTotalTokens() {
        return inputTokens + outputTokens;
    }

    public static Builder builder() { return new Builder(); }

    public static class Builder {
        private String provider;
        private String model;
        private int inputTokens;
        private int outputTokens;
        private double estimatedCost;

        public Builder provider(String provider) { this.provider = provider; return this; }
        public Builder model(String model) { this.model = model; return this; }
        public Builder inputTokens(int inputTokens) { this.inputTokens = inputTokens; return this; }
        public Builder outputTokens(int outputTokens) { this.outputTokens = outputTokens; return this; }
        public Builder estimatedCost(double estimatedCost) { this.estimatedCost = estimatedCost; return this; }

        public ModelUsage build() { return new ModelUsage(this); }
    }
}
