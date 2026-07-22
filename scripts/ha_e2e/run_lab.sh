#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HA_IMAGE="${HA_E2E_IMAGE:-ghcr.io/home-assistant/home-assistant:stable}"
HA_PORT="${HA_E2E_PORT:-8123}"
ARTIFACT_DIR="${HA_E2E_ARTIFACT_DIR:-${ROOT_DIR}/artifacts/ha-e2e}"
SCENARIO="${HA_E2E_SCENARIO:-${ROOT_DIR}/e2e/ha/scenarios/easy_lifecycle.json}"
LAB_DIR="$(mktemp -d "${TMPDIR:-/tmp}/smart-shading-ha-e2e.XXXXXX")"
CONFIG_DIR="${LAB_DIR}/config"
PACKAGE_DIR="${LAB_DIR}/package"
OLD_SOURCE_DIR="${LAB_DIR}/old-source"
OLD_PACKAGE_DIR="${LAB_DIR}/old-package"
UPGRADE_FROM_REF="${HA_E2E_UPGRADE_FROM_REF:-}"
STATE_FILE="${LAB_DIR}/runner-state.json"
CONTAINER_NAME="smart-shading-e2e-${GITHUB_RUN_ID:-local}-$$"
NETWORK_NAME="${CONTAINER_NAME}-network"
BASE_URL="http://127.0.0.1:${HA_PORT}"
CONTAINER_STARTED=0
CONTAINER_RUNNING=0
NETWORK_CREATED=0
HOST_UID="$(id -u)"
HOST_GID="$(id -g)"

mkdir -p "${CONFIG_DIR}/custom_components" "${PACKAGE_DIR}" "${ARTIFACT_DIR}"
for artifact_name in \
  configuration.yaml container-inspect.json container.log home-assistant.log \
  junit-bootstrap.xml junit-restart.xml result-bootstrap.json result-restart.json \
  lifecycle-final.json manifest-after-upgrade.json manifest-before-upgrade.json \
  registry-summary.json scenario.json snapshot-bootstrap.json snapshot-restart.json \
  test-runner.log wizard-coverage-live.json; do
  rm -f "${ARTIFACT_DIR}/${artifact_name}"
done

collect_artifacts() {
  local exit_code=$?
  set +e
  if [[ "${CONTAINER_STARTED}" == "1" ]]; then
    docker logs "${CONTAINER_NAME}" >"${ARTIFACT_DIR}/container.log" 2>&1
    docker inspect "${CONTAINER_NAME}" >"${ARTIFACT_DIR}/container-inspect.json" 2>/dev/null
    if [[ "${CONTAINER_RUNNING}" == "1" ]]; then
      docker exec "${CONTAINER_NAME}" \
        chown -R "${HOST_UID}:${HOST_GID}" /config >/dev/null 2>&1
    else
      docker run --rm --entrypoint chown \
        -v "${CONFIG_DIR}:/config" \
        "${HA_IMAGE}" -R "${HOST_UID}:${HOST_GID}" /config >/dev/null 2>&1
    fi
    docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1
  fi
  if [[ "${NETWORK_CREATED}" == "1" ]]; then
    docker network rm "${NETWORK_NAME}" >/dev/null 2>&1
  fi
  if [[ -f "${CONFIG_DIR}/home-assistant.log" ]]; then
    cp "${CONFIG_DIR}/home-assistant.log" "${ARTIFACT_DIR}/home-assistant.log"
  fi
  for registry_name in core.config_entries core.entity_registry core.device_registry; do
    if [[ -f "${CONFIG_DIR}/.storage/${registry_name}" ]]; then
      cp "${CONFIG_DIR}/.storage/${registry_name}" \
        "${ARTIFACT_DIR}/${registry_name}.json"
    fi
  done
  cp "${ROOT_DIR}/e2e/ha/configuration.yaml" "${ARTIFACT_DIR}/configuration.yaml"
  cp "${SCENARIO}" "${ARTIFACT_DIR}/scenario.json"
  rm -rf "${LAB_DIR}"
  exit "${exit_code}"
}
trap collect_artifacts EXIT

python3 "${ROOT_DIR}/scripts/build_release.py" \
  --output "${LAB_DIR}/smart_shading.zip"
python3 -m zipfile -e "${LAB_DIR}/smart_shading.zip" "${PACKAGE_DIR}"
INSTALL_PACKAGE_DIR="${PACKAGE_DIR}"
if [[ -n "${UPGRADE_FROM_REF}" ]]; then
  mkdir -p "${OLD_SOURCE_DIR}" "${OLD_PACKAGE_DIR}"
  git archive "${UPGRADE_FROM_REF}" | tar -x -C "${OLD_SOURCE_DIR}"
  python3 "${OLD_SOURCE_DIR}/scripts/build_release.py" \
    --output "${LAB_DIR}/smart_shading-old.zip"
  python3 -m zipfile -e "${LAB_DIR}/smart_shading-old.zip" "${OLD_PACKAGE_DIR}"
  INSTALL_PACKAGE_DIR="${OLD_PACKAGE_DIR}"
fi
cp -R "${INSTALL_PACKAGE_DIR}/custom_components/smart_shading" \
  "${CONFIG_DIR}/custom_components/smart_shading"
cp -R "${ROOT_DIR}/e2e/ha/fixture/custom_components/smart_shading_test_fixture" \
  "${CONFIG_DIR}/custom_components/smart_shading_test_fixture"
cp "${ROOT_DIR}/e2e/ha/configuration.yaml" "${CONFIG_DIR}/configuration.yaml"

docker network create "${NETWORK_NAME}" >/dev/null
NETWORK_CREATED=1
docker run -d \
  --name "${CONTAINER_NAME}" \
  --network "${NETWORK_NAME}" \
  --tmpfs /run:rw,exec,nosuid,size=64m \
  --tmpfs /tmp \
  -p "127.0.0.1:${HA_PORT}:8123" \
  -v "${CONFIG_DIR}:/config" \
  "${HA_IMAGE}" >/dev/null
CONTAINER_STARTED=1
CONTAINER_RUNNING=1

python3 "${ROOT_DIR}/scripts/ha_e2e/run_scenarios.py" \
  --base-url "${BASE_URL}" \
  --phase bootstrap \
  --scenario "${SCENARIO}" \
  --state-file "${STATE_FILE}" \
  --output-dir "${ARTIFACT_DIR}" 2>&1 | tee -a "${ARTIFACT_DIR}/test-runner.log"

if [[ -n "${UPGRADE_FROM_REF}" ]]; then
  cp "${CONFIG_DIR}/custom_components/smart_shading/manifest.json" \
    "${ARTIFACT_DIR}/manifest-before-upgrade.json"
  rm -rf "${CONFIG_DIR}/custom_components/smart_shading"
  cp -R "${PACKAGE_DIR}/custom_components/smart_shading" \
    "${CONFIG_DIR}/custom_components/smart_shading"
  cp "${CONFIG_DIR}/custom_components/smart_shading/manifest.json" \
    "${ARTIFACT_DIR}/manifest-after-upgrade.json"
fi

if [[ "${HA_E2E_RUN_UI:-0}" == "1" ]]; then
  HA_E2E_BASE_URL="${BASE_URL}" \
  HA_E2E_USERNAME="e2e-owner" \
  HA_E2E_PASSWORD="e2e-only-disposable-password" \
    npm --prefix "${ROOT_DIR}/e2e/ui" test
fi

docker restart "${CONTAINER_NAME}" >/dev/null

python3 "${ROOT_DIR}/scripts/ha_e2e/run_scenarios.py" \
  --base-url "${BASE_URL}" \
  --phase restart \
  --scenario "${SCENARIO}" \
  --state-file "${STATE_FILE}" \
  --output-dir "${ARTIFACT_DIR}" 2>&1 | tee -a "${ARTIFACT_DIR}/test-runner.log"

# Home Assistant persists registry changes asynchronously. Stop it cleanly before
# inspecting .storage so the audit sees the lifecycle's final registry state.
docker stop --time 30 "${CONTAINER_NAME}" >/dev/null
CONTAINER_RUNNING=0

python3 "${ROOT_DIR}/scripts/ha_e2e/check_registry.py" \
  --storage-dir "${CONFIG_DIR}/.storage" \
  --lifecycle "${ARTIFACT_DIR}/lifecycle-final.json" \
  --output "${ARTIFACT_DIR}/registry-summary.json"
