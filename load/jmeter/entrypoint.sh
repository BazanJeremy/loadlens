#!/bin/sh
# Runs JMeter and returns as soon as the test is over.
#
# JMeter 5.6.3's Open Model Thread Group starts its threads from an Executors.newCachedThreadPool()
# that is never shut down (OpenModelThreadGroup.kt, line 86, tag rel/v5.6.3). Idle threads of
# such a pool are not daemons and only end after sixty seconds, so the JVM outlives every test by
# about a minute (thread dump taken on 2026-10-17). JMeter prints "... end of run" once the test
# has ended; this wrapper stops there, and the container's exit ends the lingering JVM.
set -u

fifo="$(mktemp -u)"
mkfifo "$fifo"
jmeter "$@" >"$fifo" 2>&1 &
pid=$!

while IFS= read -r line; do
    printf '%s\n' "$line"
    if [ "$line" = "... end of run" ]; then
        exit 0
    fi
done <"$fifo"

# JMeter ended without finishing a test (invalid plan, --version, --help...): keep its exit code.
wait "$pid"
