#!/busybox/busybox sh
# shellcheck disable=SC2187

set -euo pipefail

# Concatenate two strings
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

# Load environment variables from a file
load_environment() {
    local env_file="${PLUGIN_ENV_FILE:-}"
    if [ -f "${PWD}/${env_file}" ]; then
        while IFS= read -r line; do
            export "${line?}"
        done < <(grep -v '^ *#' "${PWD}/${env_file}")
    fi
}

# Set up Docker authentication
setup_docker_auth() {
    if [ -n "${PLUGIN_USERNAME:-}" ] || [ -n "${PLUGIN_PASSWORD:-}" ]; then
        local DOCKER_AUTH=$(echo -n "${PLUGIN_USERNAME}:${PLUGIN_PASSWORD}" | base64 | tr -d '\n')

        cat > /kaniko/.docker/config.json <<DOCKERJSON
{
    "auths": {
        "${PLUGIN_REGISTRY}": {
            "auth": "${DOCKER_AUTH}"
        }
    }
}
DOCKERJSON
    fi
}

# Set up Kaniko options
setup_kaniko_options() {
    DOCKERFILE=${PLUGIN_DOCKERFILE:-Dockerfile}
    CONTEXT=${PLUGIN_CONTEXT:-$PWD}
    LOG=${PLUGIN_LOG_LEVEL:-info}
    EXTRA_OPTS=""
    if [ "${PLUGIN_SKIP_TLS_VERIFY:-}" = "true" ]; then
        EXTRA_OPTS=$(concatenate_strings "${EXTRA_OPTS}" '--skip-tls-verify=true')
    fi

    if [ "${PLUGIN_INSECURE:-}" = "true" ]; then
        EXTRA_OPTS=$(concatenate_strings "${EXTRA_OPTS}" '--insecure=true')
    fi

    if [ "${PLUGIN_INSECURE_PULL:-}" = "true" ]; then
        EXTRA_OPTS=$(concatenate_strings "${EXTRA_OPTS}" '--insecure-pull=true')
    fi

    if [ -n "${PLUGIN_INSECURE_REGISTRY:-}" ]; then
        EXTRA_OPTS=$(concatenate_strings "${EXTRA_OPTS}" "--insecure-registry=${PLUGIN_INSECURE_REGISTRY}")
    fi

    if [ "${PLUGIN_CACHE:-}" = "true" ]; then
        local CACHE="--cache=true"
    fi

    if [ -n "${PLUGIN_CACHE_REPO:-}" ]; then
        local CACHE_REPO="--cache-repo=${PLUGIN_REGISTRY}/${PLUGIN_CACHE_REPO}"
    fi

    if [ -n "${PLUGIN_CACHE_TTL:-}" ]; then
        local CACHE_TTL="--cache-ttl=${PLUGIN_CACHE_TTL}"
    fi

    if [ -n "${PLUGIN_BUILD_ARGS:-}" ]; then
        local BUILD_ARGS=$(echo "${PLUGIN_BUILD_ARGS}" | tr ',' '\n' | while read -r build_arg; do echo "--build-arg ${build_arg}"; done)
    fi

    local BUILD_ARGS_FROM_ENV=""
    if [ -n "${PLUGIN_BUILD_ARGS_FROM_ENV:-}" ]; then
        while IFS= read -r build_arg; do
            BUILD_ARGS_FROM_ENV=$(concatenate_strings "${BUILD_ARGS_FROM_ENV}" "--build-arg ${build_arg}=$(eval "echo \$$build_arg")")
        done < <(echo "${PLUGIN_BUILD_ARGS_FROM_ENV}" | tr ',' '\n')
    fi

    if [ -n "${PLUGIN_MIRRORS:-}" ]; then
        local MIRROR=$(echo "${PLUGIN_MIRRORS}" | tr ',' '\n' | while read -r mirror; do echo "--registry-mirror=${mirror}"; done)
    fi

    if [ "${PLUGIN_AUTO_TAG:-}" = "true" ]; then
        generate_tags
    fi

    if [ "${PLUGIN_IGNORE_VAR_RUN:-}" = "false" ]; then
        EXTRA_OPTS=$(concatenate_strings "${EXTRA_OPTS}" "--ignore-var-run=false")
    fi
}

# Generate tags (Global fallback tags)
generate_tags() {
    local TAG=$(echo "${CI_COMMIT_TAG:-}" | sed 's/^v//g')
    local part=$(echo "${TAG}" | tr ',' '\n' | wc -l)
    echo "${TAG}" | grep -E "[a-z-]" &>/dev/null && local isNum=1 || local isNum=0

    if [ -z "${TAG:-}" ]; then
        echo "latest" > .tags
    elif [ "${isNum}" -eq 1 ] || [ "${part}" -gt 3 ]; then
        echo "${TAG},latest" > .tags
    else
        local major=$(echo "${TAG}" | awk -F'.' '{print $1}')
        local minor=$(echo "${TAG}" | awk -F'.' '{print $2}')
        local release=$(echo "${TAG}" | awk -F'.' '{print $3}')

        major=${major:-0}
        minor=${minor:-0}
        release=${release:-0}

        echo "${major},${major}.${minor},${major}.${minor}.${release},latest" > .tags
    fi
}

# UPDATED: Determine destinations with Folder-Aware versioning
determine_destinations() {
    local file_path="${1}"
    local DESTINATIONS=""
    
    # 1. Look for the specific VERSION file created by git-cliff
    local folder_version=""
    if [ -f "${file_path}/VERSION" ]; then
        folder_version=$(cat "${file_path}/VERSION" | tr -d '\n\r ')
    fi

    if [ "${PLUGIN_DRY_RUN:-}" = "true" ] || [ -z "${PLUGIN_REPO:-}" ]; then
        DESTINATIONS="--no-push"
    
    # 2. Priority 1: Use the Folder Version if it exists
    elif [ -n "${folder_version}" ]; then
        echo "Found version ${folder_version} for ${file_path}"
        DESTINATIONS="--destination=${PLUGIN_REGISTRY}/${PLUGIN_REPO}/${file_path}:${folder_version}"
        # Also push 'latest' for this specific folder
        DESTINATIONS="${DESTINATIONS} --destination=${PLUGIN_REGISTRY}/${PLUGIN_REPO}/${file_path}:latest"
        
        # Also add global tags from YAML (like commit SHA) if provided
        if [ -n "${PLUGIN_TAGS:-}" ]; then
            local extra=$(echo "${PLUGIN_TAGS}" | tr ',' '\n' | while read -r tag; do echo "--destination=${PLUGIN_REGISTRY}/${PLUGIN_REPO}/${file_path}:${tag}"; done)
            DESTINATIONS="${DESTINATIONS} ${extra}"
        fi

    # 3. Priority 2: Fallback to YAML tags
    elif [ -n "${PLUGIN_TAGS:-}" ]; then
        DESTINATIONS=$(echo "${PLUGIN_TAGS}" | tr ',' '\n' | while read -r tag; do echo "--destination=${PLUGIN_REGISTRY}/${PLUGIN_REPO}/${file_path}:${tag}"; done)
    
    # 4. Priority 3: Fallback to .tags file logic
    elif [ -f .tags ]; then
        while IFS= read -r tag; do
            DESTINATIONS=$(concatenate_strings "${DESTINATIONS}" "--destination=${PLUGIN_REGISTRY}/${PLUGIN_REPO}/${file_path}:${tag}")
        done < <(sed -e 's/,\s*/\n/g' .tags)
    
    # 5. Final Fallback: Push as latest
    elif [ -n "${PLUGIN_REPO:-}" ]; then
        DESTINATIONS="--destination=${PLUGIN_REGISTRY}/${PLUGIN_REPO}/${file_path}:latest"
    fi
    echo "${DESTINATIONS}"
}

# Run Kaniko
kaniko() {
    local path="${1}"
    local destinations=$(determine_destinations "${path}")
    echo "================================================================"
    echo "Building path: ${path}"
    echo "Destinations:"
    echo "${destinations}" | tr ' ' '\n' | cut -d '=' -f 2-
    echo "================================================================"
    
    /kaniko/executor -v "${LOG}" \
        --context="${CONTEXT}/${path}" \
        --cleanup \
        --dockerfile="${DOCKERFILE}" \
        ${EXTRA_OPTS} \
        ${destinations} \
        "${CACHE:-}" \
        "${CACHE_TTL:-}" \
        "${CACHE_REPO:-}" \
        "${TARGET:-}" \
        ${BUILD_ARGS:-} \
        ${BUILD_ARGS_FROM_ENV:-} \
        "${MIRROR:-}"
}

# Run the script
run() {
    while IFS= read -r path; do
        # Ensure we don't process empty lines
        if [ -n "$path" ]; then
            kaniko "$path"
        fi
    done < "${PLUGIN_CHANGED_FILE}"
}

# Main function
main() {
    load_environment
    setup_docker_auth
    setup_kaniko_options
    run
}

main


