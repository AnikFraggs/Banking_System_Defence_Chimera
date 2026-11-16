# --- Build stage: compile + test the multi-module project with Maven ---
FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /workspace

# Copy POMs first for better layer caching.
COPY pom.xml .
COPY common/pom.xml common/pom.xml
COPY defense-pipeline/pom.xml defense-pipeline/pom.xml
COPY platform-api/pom.xml platform-api/pom.xml
RUN mvn -B -q dependency:go-offline || true

# Copy sources and build the bootable jar.
COPY common/src common/src
COPY defense-pipeline/src defense-pipeline/src
COPY platform-api/src platform-api/src
# gRPC stubs are generated from contracts/fraud_gate.proto (protoSourceRoot
# is ../contracts in platform-api/pom.xml); omitting it breaks compilation.
COPY contracts contracts
# Unit/integration tests run in the local + CI gate; the image build only
# produces the runtime jar, so test sources are not compiled here either.
RUN mvn -B clean package -Dmaven.test.skip=true

# --- Runtime stage: slim JRE, non-root ---
FROM eclipse-temurin:21-jre AS runtime
WORKDIR /app
RUN useradd --create-home --uid 10001 chimera
COPY --from=build /workspace/platform-api/target/platform-api-*.jar /app/app.jar
# The app creates ./datasets/uploads under WORKDIR at startup; give the
# non-root runtime user ownership of /app so directory creation succeeds.
RUN mkdir -p /app/datasets/uploads && chown -R chimera:chimera /app
USER chimera
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
