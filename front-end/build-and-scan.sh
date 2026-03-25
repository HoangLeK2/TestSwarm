#!/bin/bash

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
APP_NAME="${APP_NAME:-application-name}"
APP_TAG="${APP_TAG:-$(git rev-parse --short HEAD)-$(date +%s)}"
APP_REGISTRY="${APP_REGISTRY:-registry.pila.vn}"
GITOPS_NAMESPACE="${GITOPS_NAMESPACE:-dev}"
DOCKERFILE="${DOCKERFILE:-Dockerfile}"
BUILD_CONTEXT="${BUILD_CONTEXT:-.}"
PUSH_IMAGE="${PUSH_IMAGE:-false}"
FAIL_ON_VULN="${FAIL_ON_VULN:-true}"
TRIVY_SEVERITY="${TRIVY_SEVERITY:-HIGH,CRITICAL}"

# Construct image name
APP_IMAGE="${APP_REGISTRY}/${GITOPS_NAMESPACE}/${APP_NAME}"

echo -e "${GREEN}🐳 Docker Build & Scan Script${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "App Name:     ${APP_NAME}"
echo "Image Tag:    ${APP_TAG}"
echo "Image:        ${APP_IMAGE}:${APP_TAG}"
echo "Dockerfile:   ${DOCKERFILE}"
echo "Context:      ${BUILD_CONTEXT}"
echo "Push Image:   ${PUSH_IMAGE}"
echo "Fail on Vuln: ${FAIL_ON_VULN}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
  echo -e "${RED}❌ Docker is not running. Please start Docker and try again.${NC}"
  exit 1
fi

# Check if Trivy is available
if ! command -v trivy &> /dev/null; then
  echo -e "${YELLOW}⚠️  Trivy not found. Installing via Docker...${NC}"
  USE_DOCKER_TRIVY=true
else
  USE_DOCKER_TRIVY=false
fi

# Step 1: Build Docker image
echo -e "${GREEN}📦 Step 1: Building Docker image...${NC}"
if docker build \
  -f "${DOCKERFILE}" \
  -t "${APP_IMAGE}:${APP_TAG}" \
  -t "${APP_IMAGE}:latest" \
  "${BUILD_CONTEXT}"; then
  echo -e "${GREEN}✅ Docker image built successfully${NC}"
else
  echo -e "${RED}❌ Docker build failed${NC}"
  exit 1
fi

echo ""

# Step 2: Download Trivy HTML template
echo -e "${GREEN}🔍 Step 2: Preparing Trivy scan...${NC}"
HTML_TEMPLATE="html.tpl"
if [ ! -f "${HTML_TEMPLATE}" ]; then
  echo "Downloading Trivy HTML template..."
  curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/html.tpl -o "${HTML_TEMPLATE}" || {
    echo -e "${YELLOW}⚠️  Failed to download template, using default format${NC}"
    HTML_TEMPLATE=""
  }
fi

echo ""

# Step 3: Scan image with Trivy
echo -e "${GREEN}🔍 Step 3: Scanning image with Trivy...${NC}"
REPORT_FILE="trivy-${APP_NAME}-report.html"
SARIF_FILE="trivy-${APP_NAME}-report.sarif"
JSON_FILE="trivy-${APP_NAME}-report.json"

if [ "$USE_DOCKER_TRIVY" = true ]; then
  # Use Trivy via Docker
  echo "Running Trivy scan via Docker..."
  
  # HTML report
  docker run --rm \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v "$(pwd):/output" \
    aquasecurity/trivy:latest \
    image \
    --format template \
    --template "@/contrib/html.tpl" \
    --output "/output/${REPORT_FILE}" \
    --severity "${TRIVY_SEVERITY}" \
    "${APP_IMAGE}:${APP_TAG}" || true
  
  # SARIF report
  docker run --rm \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v "$(pwd):/output" \
    aquasecurity/trivy:latest \
    image \
    --format sarif \
    --output "/output/${SARIF_FILE}" \
    --severity "${TRIVY_SEVERITY}" \
    "${APP_IMAGE}:${APP_TAG}" || true
  
  # JSON report for parsing
  docker run --rm \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v "$(pwd):/output" \
    aquasecurity/trivy:latest \
    image \
    --format json \
    --output "/output/${JSON_FILE}" \
    --severity "${TRIVY_SEVERITY}" \
    "${APP_IMAGE}:${APP_TAG}" || true
else
  # Use local Trivy
  echo "Running Trivy scan..."
  
  if [ -n "${HTML_TEMPLATE}" ]; then
    trivy image \
      --format template \
      --template "@${HTML_TEMPLATE}" \
      --output "${REPORT_FILE}" \
      --severity "${TRIVY_SEVERITY}" \
      "${APP_IMAGE}:${APP_TAG}" || true
  else
    trivy image \
      --format table \
      --severity "${TRIVY_SEVERITY}" \
      "${APP_IMAGE}:${APP_TAG}" || true
  fi
  
  trivy image \
    --format sarif \
    --output "${SARIF_FILE}" \
    --severity "${TRIVY_SEVERITY}" \
    "${APP_IMAGE}:${APP_TAG}" || true
  
  trivy image \
    --format json \
    --output "${JSON_FILE}" \
    --severity "${TRIVY_SEVERITY}" \
    "${APP_IMAGE}:${APP_TAG}" || true
fi

echo ""

# Step 4: Check for vulnerabilities
echo -e "${GREEN}📊 Step 4: Analyzing scan results...${NC}"

if [ -f "${JSON_FILE}" ]; then
  # Parse JSON report
  VULN_COUNT=$(jq '[.Results[]?.Vulnerabilities[]?] | length' "${JSON_FILE}" 2>/dev/null || echo "0")
  CRITICAL_COUNT=$(jq '[.Results[]?.Vulnerabilities[]? | select(.Severity == "CRITICAL")] | length' "${JSON_FILE}" 2>/dev/null || echo "0")
  HIGH_COUNT=$(jq '[.Results[]?.Vulnerabilities[]? | select(.Severity == "HIGH")] | length' "${JSON_FILE}" 2>/dev/null || echo "0")
  
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "Scan Results:"
  echo "  Total Vulnerabilities: ${VULN_COUNT}"
  echo "  Critical:              ${CRITICAL_COUNT}"
  echo "  High:                  ${HIGH_COUNT}"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  
  if [ -f "${REPORT_FILE}" ]; then
    echo -e "${GREEN}📄 HTML report saved to: ${REPORT_FILE}${NC}"
  fi
  if [ -f "${SARIF_FILE}" ]; then
    echo -e "${GREEN}📄 SARIF report saved to: ${SARIF_FILE}${NC}"
  fi
  
  # Check if we should fail
  if [ "${FAIL_ON_VULN}" = "true" ] && [ "${VULN_COUNT}" -gt 0 ]; then
    echo ""
    echo -e "${RED}🛑 Vulnerabilities found in image scan!${NC}"
    echo -e "${RED}   Set FAIL_ON_VULN=false to continue despite vulnerabilities${NC}"
    exit 1
  elif [ "${VULN_COUNT}" -gt 0 ]; then
    echo ""
    echo -e "${YELLOW}⚠️  Vulnerabilities found but continuing (FAIL_ON_VULN=false)${NC}"
  else
    echo ""
    echo -e "${GREEN}✅ No vulnerabilities found!${NC}"
  fi
else
  echo -e "${YELLOW}⚠️  Could not parse scan results${NC}"
fi

echo ""

# Step 5: Push image (optional)
if [ "${PUSH_IMAGE}" = "true" ]; then
  echo -e "${GREEN}📤 Step 5: Pushing image to registry...${NC}"
  
  if [ -z "${REGISTRY_USER:-}" ] || [ -z "${REGISTRY_PASS:-}" ]; then
    echo -e "${YELLOW}⚠️  Registry credentials not set. Skipping push.${NC}"
    echo "   Set REGISTRY_USER and REGISTRY_PASS environment variables to push"
  else
    echo "Logging in to registry..."
    echo "${REGISTRY_PASS}" | docker login -u "${REGISTRY_USER}" --password-stdin "${APP_REGISTRY}" || {
      echo -e "${RED}❌ Failed to login to registry${NC}"
      exit 1
    }
    
    echo "Pushing ${APP_IMAGE}:${APP_TAG}..."
    docker push "${APP_IMAGE}:${APP_TAG}" || {
      echo -e "${RED}❌ Failed to push image${NC}"
      exit 1
    }
    
    echo "Pushing ${APP_IMAGE}:latest..."
    docker push "${APP_IMAGE}:latest" || {
      echo -e "${YELLOW}⚠️  Failed to push latest tag (non-fatal)${NC}"
    }
    
    echo -e "${GREEN}✅ Image pushed successfully${NC}"
  fi
else
  echo -e "${YELLOW}⏭️  Skipping push (PUSH_IMAGE=false)${NC}"
fi

echo ""
echo -e "${GREEN}✅ Build and scan completed successfully!${NC}"
echo ""
echo "Summary:"
echo "  Image: ${APP_IMAGE}:${APP_TAG}"
if [ -f "${REPORT_FILE}" ]; then
  echo "  Report: ${REPORT_FILE}"
fi

