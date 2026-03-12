# Neo4j Connector for Unity Catalog
Enables Databricks and Neo4j customers to maintain governance over their Neo4j graph data from Unity Catalog and federated queries across both data platforms.

##Key Benefits
- Unified analytical plane - one consistent interface for analysts across graph and relational data.
- No more loading bulk data into the graph - keep fault data, weather data, and time-series in the lakehouse; query it alongside graph data seamlessly.
- SQL-only access to graph data - Analysts query everything with standard SQL; Cypher translation happens automatically.
- Federated joins across graph + lakehouse - Unity Catalog distributes queries to both sources and joins the results.
- Materialized views as a graph cache - Schedule refreshes to avoid hitting the graph directly on every query.
- Genie natural language queries - Materialized graph views plug into Databricks Genie for natural language access across all data.

##What is it?
A single shaded (fat) JAR that bundles the Neo4j JDBC driver, the SQL-to-Cypher translator, and the Spark subquery cleaner for use with Databricks Unity Catalog federated queries.

Instead of downloading and uploading two separate JARs (`neo4j-jdbc-full-bundle` + `neo4j-jdbc-translator-sparkcleaner`), users upload this single JAR to a UC Volume and reference one path in their connection configuration.

For examples of how to set up and use this connector with Databricks Unity Catalog, see [neo4j-uc-integration](https://github.com/neo4j-partners/neo4j-uc-integration).

## Prerequisites

- Java 17+

## Build

```bash
./mvnw clean verify
```

The shaded JAR is produced at:

```
target/neo4j-unity-catalog-connector-1.0.0-SNAPSHOT.jar
```

## Run Tests

Tests verify that the bundled translators are discoverable via SPI, the Spark subquery cleaner handles Databricks/Spark query patterns, and the JDBC driver class is loadable.

```bash
./mvnw test
```

## Release

The `release` GitHub Actions workflow publishes a GitHub Release with the built JAR when you push a tag:

```bash
git tag 1.0.0
git push origin 1.0.0
```

## What's Inside

The shaded JAR bundles:

| Dependency | Purpose |
|---|---|
| `neo4j-jdbc` | Core JDBC driver for Neo4j |
| `neo4j-jdbc-translator-impl` | SQL-to-Cypher translation engine |
| `neo4j-jdbc-translator-sparkcleaner` | Cleans Spark subquery wrapping (`SPARK_GEN_SUBQ_0 WHERE 1=0`) |

All transitive dependencies (Jackson, Netty, jOOQ, Bolt protocol, Cypher DSL, Reactive Streams) are relocated under `org.neo4j.jdbc.internal.shaded.*` to avoid classpath conflicts with the Databricks runtime.

## Design

### Problem

Connecting Neo4j to Databricks Unity Catalog previously required users to download and upload **two separate JARs** to a Unity Catalog Volume:

1. `neo4j-jdbc-full-bundle-6.x.x.jar` — the main JDBC driver with SQL-to-Cypher translation
2. `neo4j-jdbc-translator-sparkcleaner-6.x.x.jar` — handles Spark's subquery wrapping (`SPARK_GEN_SUBQ_0 WHERE 1=0`)

Both had to be referenced individually in the `java_dependencies` array when creating a UC JDBC connection. This meant two manual downloads from Maven Central, two uploads to a Volume, two paths to manage, and two version numbers to keep in sync. If a user forgot the sparkcleaner JAR or used mismatched versions, the connection silently broke with confusing errors.

### Solution

This project uses `maven-shade-plugin` to merge all three dependencies (`neo4j-jdbc`, `neo4j-jdbc-translator-impl`, `neo4j-jdbc-translator-sparkcleaner`) into a single self-contained JAR. Users upload one file to a UC Volume and reference one path — no version coordination, no missing dependencies.

### SPI Service Registration

Java's Service Provider Interface (SPI) is a plugin mechanism built into the JDK. A library declares an interface (in this case, `TranslatorFactory`) and other JARs provide implementations of that interface. At runtime, `java.util.ServiceLoader` discovers these implementations automatically by reading text files under `META-INF/services/` inside the JAR. Each file is named after the interface and lists the fully qualified class names of the implementations.

The Neo4j JDBC driver uses SPI to discover SQL translators. When the driver starts, it calls `ServiceLoader.load(TranslatorFactory.class)` which scans the classpath for `META-INF/services/org.neo4j.jdbc.translator.spi.TranslatorFactory` files. Any translator factory listed in those files gets loaded and used in the translation pipeline.

This project bundles two translator JARs that each provide their own SPI registration:

- `neo4j-jdbc-translator-impl` registers `SqlToCypherTranslatorFactory` — converts SQL to Cypher
- `neo4j-jdbc-translator-sparkcleaner` registers `SparkSubqueryCleaningTranslatorFactory` — strips Spark's `SPARK_GEN_SUBQ_0 WHERE 1=0` wrapping before translation

When the maven-shade-plugin merges these JARs into one, it uses `ServicesResourceTransformer` to concatenate the separate SPI files into a single merged file. Without this transformer, one file would overwrite the other and only one translator would be discovered at runtime.

If a custom `DatabricksTranslator` is needed in the future to handle Databricks-specific SQL patterns beyond what the Spark cleaner covers, it can be added by implementing `TranslatorFactory` and registering it via the same SPI mechanism.

### User-Agent Identification

The project includes a `META-INF/neo4j-jdbc-user-agent.txt` file containing:

```
neo4j-unity-catalog-connector/${project.version}
```

This string is sent by the Neo4j JDBC driver to the Neo4j server with every connection. The `${project.version}` placeholder is substituted by Maven at build time (via `<filtering>true</filtering>` in the pom.xml). This lets Neo4j (especially Aura) distinguish connections coming from the Databricks UC connector vs the plain JDBC driver — useful for support, usage analytics, and debugging.

### Package Relocation

All bundled dependencies are relocated under `org.neo4j.jdbc.internal.shaded.*` to avoid classpath conflicts with whatever JARs are already on the Databricks SafeSpark sandbox classpath.
