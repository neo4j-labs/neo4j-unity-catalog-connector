package org.neo4j.uc;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.Comparator;
import java.util.Map;
import java.util.ServiceLoader;
import java.util.stream.Collectors;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.neo4j.jdbc.translator.spi.Translator;
import org.neo4j.jdbc.translator.spi.TranslatorFactory;

class BundledTranslatorsTest {

    @Test
    void shouldDiscoverAllTranslatorFactories() {
        var factories = ServiceLoader.load(TranslatorFactory.class).stream()
                .map(ServiceLoader.Provider::get)
                .collect(Collectors.toList());

        var classNames =
                factories.stream().map(f -> f.getClass().getSimpleName()).collect(Collectors.toList());

        assertTrue(
                classNames.contains("SqlToCypherTranslatorFactory"),
                "Expected SqlToCypherTranslatorFactory, found: " + classNames);
        assertTrue(
                classNames.contains("SparkSubqueryCleaningTranslatorFactory"),
                "Expected SparkSubqueryCleaningTranslatorFactory, found: " + classNames);
    }

    @Test
    void shouldCreateTranslatorsFromFactories() {
        var factories = ServiceLoader.load(TranslatorFactory.class).stream()
                .map(ServiceLoader.Provider::get)
                .collect(Collectors.toList());

        for (var factory : factories) {
            Translator translator = factory.create(Map.of());
            assertNotNull(translator, "Factory " + factory.getClass().getSimpleName() + " returned null");
        }
    }

    @ParameterizedTest
    @ValueSource(
            strings = {
                "SELECT * FROM (SELECT * FROM some_table) SPARK_GEN_SUBQ_0 WHERE 1=0",
                "SELECT * FROM (SELECT * FROM some_table) SPARK_GEN_SUBQ_0 WHERE 1 = 0",
                "SELECT * FROM (SELECT col1, col2 FROM some_table) SPARK_GEN_SUBQ_0 WHERE 1=0"
            })
    void translatorPipelineShouldHandleSparkQueries(String sparkQuery) {
        // The translator pipeline processes queries in order: the spark cleaner runs first
        // (highest precedence) to strip Spark subquery wrapping, then the SQL-to-Cypher
        // translator converts the cleaned SQL to Cypher. A translator returns null when it
        // does not handle the input, passing it to the next translator in the chain.
        var translators = ServiceLoader.load(TranslatorFactory.class).stream()
                .map(ServiceLoader.Provider::get)
                .map(f -> f.create(Map.of()))
                .sorted(Comparator.comparingInt(Translator::getOrder))
                .collect(Collectors.toList());

        String result = sparkQuery;
        for (var translator : translators) {
            String translated = translator.translate(result);
            if (translated != null) {
                result = translated;
            }
        }

        // After the full pipeline, the Spark wrapping should be gone and the result
        // should be Cypher (or at minimum, the cleaned inner query)
        assertTrue(
                !result.contains("SPARK_GEN_SUBQ"),
                "Expected SPARK_GEN_SUBQ to be removed after pipeline, got: " + result);
    }

    @Test
    void sparkCleanerShouldNotThrowOnPlainCypher() {
        var sparkCleaner = ServiceLoader.load(TranslatorFactory.class).stream()
                .map(ServiceLoader.Provider::get)
                .filter(f -> f.getClass().getSimpleName().equals("SparkSubqueryCleaningTranslatorFactory"))
                .findFirst()
                .orElseThrow()
                .create(Map.of());

        // The spark cleaner should return null (pass-through) for queries it doesn't handle
        assertDoesNotThrow(() -> sparkCleaner.translate("MATCH (n) RETURN n LIMIT 10"));
    }

    @Test
    void jdbcDriverShouldBeLoadable() throws Exception {
        Class<?> driver = Class.forName("org.neo4j.jdbc.Neo4jDriver");
        assertNotNull(driver);
    }
}
