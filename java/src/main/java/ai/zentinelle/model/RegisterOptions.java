package ai.zentinelle.model;

import java.util.List;
import java.util.Map;

/**
 * Options for agent registration.
 */
public class RegisterOptions {

    private final List<String> capabilities;
    private final Map<String, Object> metadata;
    private final String name;

    private RegisterOptions(Builder builder) {
        this.capabilities = builder.capabilities != null ? builder.capabilities : List.of();
        this.metadata = builder.metadata != null ? builder.metadata : Map.of();
        this.name = builder.name;
    }

    public List<String> getCapabilities() { return capabilities; }
    public Map<String, Object> getMetadata() { return metadata; }
    public String getName() { return name; }

    public static Builder builder() { return new Builder(); }

    public static class Builder {
        private List<String> capabilities;
        private Map<String, Object> metadata;
        private String name;

        public Builder capabilities(List<String> capabilities) { this.capabilities = capabilities; return this; }
        public Builder metadata(Map<String, Object> metadata) { this.metadata = metadata; return this; }
        public Builder name(String name) { this.name = name; return this; }

        public RegisterOptions build() { return new RegisterOptions(this); }
    }
}
