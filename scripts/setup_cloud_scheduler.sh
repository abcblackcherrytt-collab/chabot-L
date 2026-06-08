#!/bin/bash
# Cloud Scheduler setup script
# Cloud Scheduler設定スクリプト

set -e

# Configuration
PROJECT_ID="${PROJECT_ID:-your-project-id}"
REGION="${REGION:-asia-northeast1}"
SERVICE_NAME="${SERVICE_NAME:-chabot-service}"
SERVICE_ACCOUNT="${SERVICE_ACCOUNT:-chabot-sa@PROJECT_ID.iam.gserviceaccount.com}"
JOB_NAME="${JOB_NAME:-token-cleanup-job}"
SCHEDULE="${SCHEDULE:-0 3 * * *}"  # 毎日AM3:00

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if gcloud is installed
if ! command -v gcloud &> /dev/null; then
    log_error "gcloud CLI is not installed"
    exit 1
fi

# Check if user is authenticated
log_info "Checking authentication..."
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q "@"; then
    log_error "User is not authenticated. Run: gcloud auth login"
    exit 1
fi

# Set the project
log_info "Setting project to ${PROJECT_ID}..."
gcloud config set project ${PROJECT_ID}

# Enable Cloud Scheduler API
log_info "Enabling Cloud Scheduler API..."
gcloud services enable cloudscheduler.googleapis.com

# Get service URL
SERVICE_URL=$(gcloud run services describe ${SERVICE_NAME} --region=${REGION} --format='value(status.url)')
if [ -z "${SERVICE_URL}" ]; then
    log_error "Service ${SERVICE_NAME} not found in region ${REGION}"
    exit 1
fi

# Create Cloud Scheduler job
log_info "Creating Cloud Scheduler job for token cleanup..."
gcloud scheduler jobs create http ${JOB_NAME} \
    --schedule="${SCHEDULE}" \
    --time-zone="Asia/Tokyo" \
    --location=${REGION} \
    --uri="${SERVICE_URL}/api/v1/admin/cleanup-tokens" \
    --http-method=POST \
    --headers="Content-Type=application/json" \
    --oauth-service-account-email=${SERVICE_ACCOUNT} \
    --description="Daily token cleanup job at 3:00 AM"

log_info "Cloud Scheduler job created successfully!"
log_info "Job Name: ${JOB_NAME}"
log_info "Schedule: ${SCHEDULE} (daily at 3:00 AM JST)"
log_info "Time Zone: Asia/Tokyo"
log_info "Target URL: ${SERVICE_URL}/api/v1/admin/cleanup-tokens"

# Provide additional information
log_info ""
log_info "To verify the job was created:"
log_info "  gcloud scheduler jobs describe ${JOB_NAME} --location=${REGION}"
log_info ""
log_info "To manually trigger the job:"
log_info "  gcloud scheduler jobs run ${JOB_NAME} --location=${REGION}"
log_info ""
log_info "To update the schedule:"
log_info "  gcloud scheduler jobs update ${JOB_NAME} --location=${REGION} --schedule='0 3 * * *'"
log_info ""
log_info "To delete the job:"
log_info "  gcloud scheduler jobs delete ${JOB_NAME} --location=${REGION}"
