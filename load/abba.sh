#!/usr/bin/env bash
# Baseline and candidate on the same machine, interleaved A B B A.
#
#   load/abba.sh <candidate> <output-dir>
#
# <candidate>: none (A/A: the candidate is the baseline), N_PLUS_ONE, LOCK or POOL (the candidate
# runs with that SUT_REGRESSION_* switch on). Before every segment the database is reloaded and
# the API recreated, so each segment starts from the same state. Writes A1/B1/B2/A2 .jtl and .log
# files and meta.json to <output-dir>.
#
# Settings (environment): RAMP_S (10), HOLD_S (60), RATE_CREATE_PAYMENT (4), RATE_GET_PAYMENT
# (10), RATE_GET_STATEMENT (6), JMETER_IMAGE (loadlens-jmeter:5.6.3).
#
# SUT_IMAGE_BASELINE and SUT_IMAGE_CANDIDATE (both or neither): local images of the system under
# test that the A and the B segments run, seed and API alike, e.g. a pull request's base commit
# against its head. Each is tagged as the compose images (loadlens-sut-seed, loadlens-sut-api)
# before its segment, which then starts with --no-build. Without them, every segment runs the
# images compose already built. Either way meta.json records the image each API container ran.
set -euo pipefail

candidate="${1:?candidate: none, N_PLUS_ONE, LOCK or POOL}"
out="${2:?output directory}"
case "$candidate" in
    none | N_PLUS_ONE | LOCK | POOL) ;;
    *) echo "unknown candidate: $candidate" >&2; exit 2 ;;
esac

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ramp_s="${RAMP_S:-10}"
hold_s="${HOLD_S:-60}"
rate_create="${RATE_CREATE_PAYMENT:-4}"
rate_get="${RATE_GET_PAYMENT:-10}"
rate_statement="${RATE_GET_STATEMENT:-6}"
image="${JMETER_IMAGE:-loadlens-jmeter:5.6.3}"
sut_baseline="${SUT_IMAGE_BASELINE:-}"
sut_candidate="${SUT_IMAGE_CANDIDATE:-}"
if { [ -n "$sut_baseline" ] && [ -z "$sut_candidate" ]; } ||
    { [ -z "$sut_baseline" ] && [ -n "$sut_candidate" ]; }; then
    echo "set both SUT_IMAGE_BASELINE and SUT_IMAGE_CANDIDATE, or neither" >&2; exit 2
fi

mkdir -p "$out"
out="$(cd "$out" && pwd)"
chmod 777 "$out" # the JMeter container runs as another user

# Docker Desktop on Windows (Git Bash) needs Windows paths for bind mounts; Linux keeps them as is.
hostpath() {
    if command -v cygpath >/dev/null 2>&1; then cygpath -w "$1"; else printf '%s' "$1"; fi
}

segment() {
    local name="$1" regression="$2" sut_image="$3" build_flag=""
    export SUT_REGRESSION_N_PLUS_ONE=0 SUT_REGRESSION_LOCK=0 SUT_REGRESSION_POOL=0
    if [ "$regression" != none ]; then
        export "SUT_REGRESSION_${regression}=1"
    fi
    if [ -n "$sut_image" ]; then
        docker tag "$sut_image" loadlens-sut-seed
        docker tag "$sut_image" loadlens-sut-api
        build_flag="--no-build"
    fi
    # shellcheck disable=SC2086 # $build_flag is empty or a single flag
    docker compose --progress quiet -f "$root/compose.yaml" up -d --wait --force-recreate \
        $build_flag seed api
    local api_image
    api_image="$(docker inspect --format '{{.Image}}' \
        "$(docker compose -f "$root/compose.yaml" ps -q api)")"
    api_images="${api_images:+$api_images, }\"$name\": \"$api_image\""
    echo "segment $name ($regression) started $(date -u +%FT%TZ)"
    local t0 t1
    t0="$(date +%s)"
    MSYS_NO_PATHCONV=1 docker run --rm --network loadlens-sut_default \
        -v "$(hostpath "$root/load/jmeter"):/plan:ro" -v "$(hostpath "$out"):/out" "$image" \
        -n -t /plan/loadlens.jmx -q /plan/loadlens.properties \
        -l "/out/$name.jtl" -j "/out/$name.log" -Jhost=api \
        -Jramp_s="$ramp_s" -Jhold_s="$hold_s" \
        -Jrate_create_payment="$rate_create" -Jrate_get_payment="$rate_get" \
        -Jrate_get_statement="$rate_statement" | grep '^summary =' | tail -1
    t1="$(date +%s)"
    # Wall-clock duration on the host: the JTL's own timestamps cannot reveal a suspended host
    # (observed 2026-10-17: a 4.5-hour sleep left a JTL spanning 64 s).
    wall_s="${wall_s:+$wall_s, }\"$name\": $((t1 - t0))"
}

started="$(date -u +%FT%TZ)"
wall_s=""
api_images=""
segment A1 none "$sut_baseline"
segment B1 "$candidate" "$sut_candidate"
segment B2 "$candidate" "$sut_candidate"
segment A2 none "$sut_baseline"

cat >"$out/meta.json" <<EOF
{
  "candidate": "$candidate",
  "order": ["A1", "B1", "B2", "A2"],
  "baseline": ["A1", "A2"],
  "candidate_segments": ["B1", "B2"],
  "ramp_s": $ramp_s,
  "hold_s": $hold_s,
  "rates": {"create_payment": $rate_create, "get_payment": $rate_get, "get_statement": $rate_statement},
  "segment_wall_s": {$wall_s},
  "sut_images": {"baseline": "${sut_baseline:-compose}", "candidate": "${sut_candidate:-compose}"},
  "segment_api_image": {$api_images},
  "jmeter_image": "$image",
  "started_at": "$started",
  "finished_at": "$(date -u +%FT%TZ)",
  "commit": "$(git -C "$root" rev-parse HEAD 2>/dev/null || echo unknown)",
  "cpu_count": $(nproc 2>/dev/null || echo null)
}
EOF
echo "done: $out"
