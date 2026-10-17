# Apache JMeter in a container: same runtime locally (no local Java needed) and in CI.
FROM eclipse-temurin:21-jre-noble@sha256:435763596c3be2b929e8bb4282520849804715c3483cfffaa323a7433f2caf71

ARG JMETER_VERSION=5.6.3
# Official checksum: https://archive.apache.org/dist/jmeter/binaries/apache-jmeter-5.6.3.tgz.sha512
ARG JMETER_SHA512=5978a1a35edb5a7d428e270564ff49d2b1b257a65e17a759d259a9283fc17093e522fe46f474a043864aea6910683486340706d745fcdf3db1505fd71e689083

RUN set -eux; \
    curl -fsSL "https://archive.apache.org/dist/jmeter/binaries/apache-jmeter-${JMETER_VERSION}.tgz" -o /tmp/jmeter.tgz; \
    echo "${JMETER_SHA512}  /tmp/jmeter.tgz" | sha512sum -c -; \
    tar -xzf /tmp/jmeter.tgz -C /opt; \
    rm /tmp/jmeter.tgz; \
    useradd --create-home --uid 10001 jmeter

ENV PATH="/opt/apache-jmeter-${JMETER_VERSION}/bin:${PATH}"
USER jmeter
WORKDIR /work
ENTRYPOINT ["jmeter"]
