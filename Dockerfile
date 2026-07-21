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
RUN mvn -B clean package

# --- Runtime stage: slim JRE, non-root ---
FROM eclipse-temurin:21-jre AS runtime
WORKDIR /app
RUN useradd --create-home --uid 10001 chimera
COPY --from=build /workspace/platform-api/target/platform-api-*.jar /app/app.jar
USER chimera
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
