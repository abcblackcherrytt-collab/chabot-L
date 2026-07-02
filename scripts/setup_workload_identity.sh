#!/bin/bash
# Workload Identity setup script
# Workload Identity設定スクリプト

set -e

# Configuration
PROJECT_ID="${PROJECT_ID:-your-project-id}"
REGION="${REGION:-asia-northeast1}"
SERVICE_NAME="${SERVICE_NAME:-chabot-service}"
SERVICE_ACCOUNT="${SERVICE_ACCOUNT:-chabot-sa@PROJECT_ID.iam.gserviceaccount.com}"

# Google Cloud services
VERTEX_AI_SERVICE_ACCOUNT="${VERTEX_AI_SERVICE_ACCOUNT:-service-PROJECT_NUMBER@gcp-sa-aiplatform.iam.gserviceaccount.com}"
STRIPE_SECRET_ID="${STRIPE_SECRET_ID:-stripe-secret-key}"
LINE_SECRET_ID="${LINE_SECRET_ID:-line-channel-secret}"

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

# Get the service account name without project ID
SA_NAME=$(echo ${SERVICE_ACCOUNT} | cut -d'@' -f1)

# Check if service account exists
log_info "Checking service account..."
if ! gcloud iam service-accounts describe ${SERVICE_ACCOUNT} &>/dev/null; then
    log_error "Service account ${SERVICE_ACCOUNT} does not exist"
    log_error "Create it with: gcloud iam service-accounts create ${SA_NAME}"
    exit 1
fi

# Get the Cloud Run service email
RUN_SERVICE_EMAIL=$(gcloud run services describe ${SERVICE_NAME} --region=${REGION} --format='value(spec.template.spec.serviceAccountName)')

# Enable required APIs
log_info "Enabling required APIs..."
gcloud services enable \
    iam.googleapis.com \
    aiplatform.googleapis.com \
    secretmanager.googleapis.com \
    sqladmin.googleapis.com

# Step 1: Grant Cloud Run service account permission to impersonate Vertex AI service account
log_info "Granting Cloud Run service account permission to impersonate Vertex AI service account..."
gcloud iam service-accounts add-iam-policy-binding ${VERTEX_AI_SERVICE_ACCOUNT} \
    --role="roles/aiplatform.user" \
    --member="serviceAccount:${SERVICE_ACCOUNT}" \
    --project=${PROJECT_ID}

# Step 2: Grant Cloud Run service account access to Vertex AI API
log_info "Granting Cloud Run service account access to Vertex AI API..."
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
    --role="roles/aiplatform.user" \
    --member="serviceAccount:${SERVICE_ACCOUNT}"

# Step 3: Grant Cloud Run service account access to Secret Manager
log_info "Granting Cloud Run service account access to Secret Manager..."
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
    --role="roles/secretmanager.secretAccessor" \
    --member="serviceAccount:${SERVICE_ACCOUNT}"

# Step 4: Grant Cloud Run service account access to specific secrets (more restrictive)
log_info "Granting Cloud Run service account access to specific secrets..."
gcloud secrets add-iam-policy-binding ${STRIPE_SECRET_ID} \
    --role="roles/secretmanager.secretAccessor" \
    --member="serviceAccount:${SERVICE_ACCOUNT}"

gcloud secrets add-iam-policy-binding ${LINE_SECRET_ID} \
    --role="roles/secretmanager.secretAccessor" \
    --member="serviceAccount:${SERVICE_ACCOUNT}"

# Step 5: Grant Cloud Run service account access to Cloud SQL (if using Cloud SQL)
log_info "Granting Cloud Run service account access to Cloud SQL..."
# Assuming Cloud SQL instance name is chabot-db
# Adjust this to your actual Cloud SQL instance name
# gcloud projects add-iam-policy-binding ${PROJECT_ID} \
#     --role="roles/cloudsql.client" \
#     --member="serviceAccount:${SERVICE_ACCOUNT}"

log_info "Workload Identity setup completed successfully!"
log_info ""
log_info "Service Account: ${SERVICE_ACCOUNT}"
log_info "Cloud Run Service: ${SERVICE_NAME}"
log_info "Region: ${REGION}"
log_info ""
log_info "The Cloud Run service can now:"
log_info "  1. Access Vertex AI API without service account JSON keys"
log_info "  2. Access Secret Manager secrets"
log_info "  3. Access Cloud SQL (if configured)"
log_info ""
log_info "Important: Do NOT include service account JSON files in the Docker image!"
