#!/bin/sh
# shellcheck disable=SC2187

set -euo pipefail

# Always uses --isolation=rootless and --storage-driver=overlay — no other
# isolation or storage driver is ever used.

concatenate_strings() {
    local _STR1="${1}"
    local _STR2="${2}"

    if [ -n "${_STR1}" ]; then
        _STR1="${_STR1} ${_STR2}"
    else
        _STR1="${_STR2}"
    fi

    echo "${_STR1}"
}

load_environment() {
    local env_file="${PLUGIN_ENV_FILE:-}"
    if [ -f "${PWD}/${env_file}" ]; then
        # shellcheck disable=SC3001
        while IFS= read -r line; do
            export "${line?}"
        done < <(grep -v '^ *#' < "${PWD}/${env_file}")
    fi
}

setup_docker_auth() {
    if [ -n "${PLUGIN_USERNAME:-}" ] || [ -n "${PLUGIN_PASSWORD:-}" ]; then
        local tls_flag="--tls-verify=true"
        [ "${PLUGIN_INSECURE:-}" = "true" ] && tls_flag="--tls-verify=false"

        buildah login \
            --username "${PLUGIN_USERNAME}" \
            --password "${PLUGIN_PASSWORD}" \
            ${tls_flag} \
            "${REGISTRY}"
    fi
}

setup_buildah_options() {
    DOCKERFILE=${PLUGIN_DOCKERFILE:-Dockerfile}
    CONTEXT=${PLUGIN_CONTEXT:-$PWD}
    LOG=${PLUGIN_LOG_LEVEL:-info}

    EXTRA_OPTS=""

    if [ "${PLUGIN_INSECURE:-}" = "true" ]; then
        TLS_VERIFY="false"
    else
        TLS_VERIFY="true"
    fi

    if [ "${PLUGIN_INSECURE_PULL:-}" = "true" ]; then
        EXTRA_OPTS=$(concatenate_strings "${EXTRA_OPTS}" "--tls-verify=false")
    fi

    if [ "${PLUGIN_CACHE:-}" = "true" ]; then
        EXTRA_OPTS=$(concatenate_strings "${EXTRA_OPTS}" "--layers=true")
        if [ -n "${PLUGIN_CACHE_REPO:-}" ]; then
            EXTRA_OPTS=$(concatenate_strings "${EXTRA_OPTS}" "--cache-from=${REGISTRY}/${PLUGIN_CACHE_REPO}")
        fi
        if [ -n "${PLUGIN_CACHE_TTL:-}" ]; then
            EXTRA_OPTS=$(concatenate_strings "${EXTRA_OPTS}" "--cache-ttl=${PLUGIN_CACHE_TTL}")
        fi
    fi

    BUILD_ARGS=""
    if [ -n "${PLUGIN_BUILD_ARGS:-}" ]; then
        BUILD_ARGS=$(echo "${PLUGIN_BUILD_ARGS}" | tr ',' '\n' | while read -r build_arg; do echo "--build-arg ${build_arg}"; done)
    fi

    BUILD_ARGS_FROM_ENV=""
    if [ -n "${PLUGIN_BUILD_ARGS_FROM_ENV:-}" ]; then
        # shellcheck disable=SC3001
        while IFS= read -r build_arg; do
            BUILD_ARGS_FROM_ENV=$(concatenate_strings "${BUILD_ARGS_FROM_ENV}" "--build-arg ${build_arg}=$(eval "echo \$$build_arg")")
        done < <(echo "${PLUGIN_BUILD_ARGS_FROM_ENV}" | tr ',' '\n')
    fi

    if [ "${PLUGIN_AUTO_TAG:-}" = "true" ]; then
        generate_tags
    fi
}

generate_tags() {
    local TAG
    TAG=$(echo "${CI_COMMIT_TAG:-}" | sed 's/v//g')
    local part
    part=$(echo "${TAG}" | tr '.' '\n' | wc -l)
    # shellcheck disable=SC3020
    echo "${TAG}" | grep -E "^[0-9.-]*$" &>/dev/null && local isNum=1 || local isNum=0

    if [ -z "${TAG:-}" ]; then
        echo "latest" > .tags
    elif [ "${isNum}" -eq 1 ] || [ "${part}" -gt 3 ]; then
        echo "${TAG},latest" > .tags
    else
        local major minor release
        major=$(echo "${TAG}" | awk -F '.' '{print $1}')
        minor=$(echo "${TAG}" | awk -F '.' '{print $2}')
        release=$(echo "${TAG}" | awk -F '.' '{print $3}')
        major=${major:-0}
        minor=${minor:-0}
        release=${release:-0}
        echo "${major},${major}.${minor},${major}.${minor}.${release},latest" > .tags
    fi
}

# Returns newline-separated list of full image refs, or the sentinel "__nopush__".
collect_destinations() {
    local file_path="${1}"
    local image_base

    if [ "${PLUGIN_DRY_RUN:-}" = "true" ]; then
        echo "__nopush__"
        return
    fi

    if [ -n "${PLUGIN_REPO:-}" ]; then
        image_base="${REGISTRY}/${PLUGIN_REPO}/${file_path}"
    else
        image_base="${REGISTRY}/${file_path}"
    fi

    if [ -n "${PLUGIN_TAGS:-}" ]; then
        echo "${PLUGIN_TAGS}" | tr ',' '\n' | while read -r tag; do
            echo "${image_base}:${tag}"
        done
    elif [ -f .tags ]; then
        sed -e 's/,/\n/g' .tags | while IFS= read -r tag; do
            echo "${image_base}:${tag}"
        done
    else
        echo "${image_base}:latest"
    fi
}

buildah_build() {
    local path="${1}"
    local destinations
    destinations="$(collect_destinations "${path}")"
    local aliases="${PLUGIN_ALIASES:-}"

    local first_tag=""
    if [ "${destinations}" != "__nopush__" ]; then
        first_tag="$(echo "${destinations}" | head -n1)"
    fi

    local image_base
    if [ -n "${PLUGIN_REPO:-}" ]; then
        image_base="${REGISTRY}/${PLUGIN_REPO}/${path}"
    else
        image_base="${REGISTRY}/${path}"
    fi

    echo "=========================================================================="
    if [ "${destinations}" = "__nopush__" ]; then
        echo "(dry-run / no-push — context: ${CONTEXT}/${path})"
    else
        echo "${destinations}"
        [ -n "${aliases}" ] && echo "aliases: ${aliases}"
    fi
    echo "=========================================================================="

    # shellcheck disable=SC2086
    buildah bud \
        --isolation rootless \
        --storage-driver overlay \
        --log-level "${LOG}" \
        ${EXTRA_OPTS} \
        --file "${CONTEXT}/${path}/${DOCKERFILE}" \
        ${first_tag:+--tag "${first_tag}"} \
        "${CONTEXT}/${path}" \
        ${BUILD_ARGS:-} \
        ${BUILD_ARGS_FROM_ENV:-}

    if [ "${destinations}" = "__nopush__" ]; then
        echo ">>> Dry-run: skipping push"
        return
    fi

    buildah push --tls-verify="${TLS_VERIFY}" "${first_tag}"

    echo "${destinations}" | tail -n +2 | while IFS= read -r extra; do
        [ -z "${extra}" ] && continue
        buildah tag "${first_tag}" "${extra}"
        buildah push --tls-verify="${TLS_VERIFY}" "${extra}"
    done

    if [ -n "${aliases}" ]; then
        while IFS= read -r alias_tag; do
            alias_tag="$(printf '%s' "${alias_tag}" | tr -d ' ')"
            [ -z "${alias_tag}" ] && continue
            local full_alias="${image_base}:${alias_tag}"
            buildah tag "${first_tag}" "${full_alias}"
            buildah push --tls-verify="${TLS_VERIFY}" "${full_alias}"
            echo ">>> Pushed alias: ${full_alias}"
        done << ALIASES
$(printf '%s' "${aliases}" | tr ',' '\n')
ALIASES
    fi
}

run() {
    while IFS= read -r path; do
        buildah_build "${path}"
    done < "${PLUGIN_CHANGED_FILE}"
}

main() {
    REGISTRY="${PLUGIN_REGISTRY:-index.docker.io}"
    load_environment
    setup_docker_auth
    setup_buildah_options
    run
}

main
