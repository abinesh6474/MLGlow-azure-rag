#!/bin/bash
set -e  # exit immediately if a command fails
set -x  # print each command before executing it

# Initialize variables
RES_GROUP=""
ACR_NAME=""
ACI_NAME=""
AKV_NAME=$ACR_NAME-vault
WORKSPACE_NAME=""

WORKSPACE_ID=$(az monitor log-analytics workspace show \
  --resource-group $RES_GROUP \
  --workspace-name $WORKSPACE_NAME \
  --query customerId -o tsv)

WORKSPACE_KEY=$(az monitor log-analytics workspace get-shared-keys \
  --resource-group $RES_GROUP \
  --workspace-name $WORKSPACE_NAME \
  --query primarySharedKey -o tsv)

echo "Resource Group: $RES_GROUP"
echo "ACR Name: $ACR_NAME"
echo "ACI Name: $ACI_NAME"
echo "Key Vault: $AKV_NAME"
echo "Workspace ID: $WORKSPACE_ID"
echo "Workspace Key: $WORKSPACE_KEY"

USER_IDENTITY_ID=$(az identity list --query "[?clientId=='$(az keyvault secret show --vault-name $AKV_NAME --name AZURE-CLIENT-ID --query value -o tsv)'].id | [0]" -o tsv)

az container delete \
  --resource-group $RES_GROUP \
  --name $ACI_NAME -y

az container create \
  --resource-group $RES_GROUP \
  --name $ACI_NAME \
  --image $ACR_NAME.azurecr.io/$ACR_NAME:latest \
  --log-analytics-workspace $WORKSPACE_ID \
  --log-analytics-workspace-key $WORKSPACE_KEY \
  --registry-login-server $ACR_NAME.azurecr.io \
  --registry-username $(az keyvault secret show --vault-name $AKV_NAME --name $ACR_NAME-pull-usr --query value -o tsv) \
  --registry-password $(az keyvault secret show --vault-name $AKV_NAME --name $ACR_NAME-pull-pwd --query value -o tsv) \
  --secure-environment-variables \
    PORT=80 \
    RUNNING_IN_PRODUCTION=true \
    AZURE_CLIENT_ID=$(az keyvault secret show --vault-name $AKV_NAME --name AZURE-CLIENT-ID --query value -o tsv) \
    AZURE_AI_CHAT_DEPLOYMENT_NAME=$(az keyvault secret show --vault-name $AKV_NAME --name AZURE-AI-CHAT-DEPLOYMENT-NAME --query value -o tsv) \
    AZURE_AI_EMBED_DEPLOYMENT_NAME=$(az keyvault secret show --vault-name $AKV_NAME --name AZURE-AI-EMBED-DEPLOYMENT-NAME --query value -o tsv) \
    AZURE_AI_EMBED_DIMENSIONS=$(az keyvault secret show --vault-name $AKV_NAME --name AZURE-AI-EMBED-DIMENSIONS --query value -o tsv) \
    AZURE_AI_SEARCH_ENDPOINT=$(az keyvault secret show --vault-name $AKV_NAME --name AZURE-AI-SEARCH-ENDPOINT --query value -o tsv) \
    AZURE_AI_SEARCH_INDEX_NAME=$(az keyvault secret show --vault-name $AKV_NAME --name AZURE-AI-SEARCH-INDEX-NAME --query value -o tsv) \
    AZURE_AI_SEARCH_API_KEY=$(az keyvault secret show --vault-name $AKV_NAME --name AZURE-AI-SEARCH-API-KEY --query value -o tsv) \
    AZURE_EXISTING_AIPROJECT_ENDPOINT=$(az keyvault secret show --vault-name $AKV_NAME --name AZURE-EXISTING-AIPROJECT-ENDPOINT --query value -o tsv) \
    AZURE_EXISTING_AIPROJECT_API_KEY=$(az keyvault secret show --vault-name $AKV_NAME --name AZURE-EXISTING-AIPROJECT-API-KEY --query value -o tsv) \
    AZURE_OPENAI_ENDPOINT=$(az keyvault secret show --vault-name $AKV_NAME --name AZURE-OPENAI-ENDPOINT --query value -o tsv) \
    AZURE_OPENAI_API_KEY=$(az keyvault secret show --vault-name $AKV_NAME --name AZURE-OPENAI-API-KEY --query value -o tsv) \
    ENABLE_AZURE_MONITOR_TRACING=$(az keyvault secret show --vault-name $AKV_NAME --name ENABLE-AZURE-MONITOR-TRACING --query value -o tsv) \
    AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED=$(az keyvault secret show --vault-name $AKV_NAME --name AZURE-TRACING-GEN-AI-CONTENT-RECORDING-ENABLED --query value -o tsv) \
    AZURE_TENANT_ID=$(az keyvault secret show --vault-name $AKV_NAME --name AZURE-TENANT-ID --query value -o tsv) \
    APPINSIGHTS_CONNECTION_STRING=$(az keyvault secret show --vault-name $AKV_NAME --name APPINSIGHTS-CONNECTION-STRING --query value -o tsv) \
    OTEL_TRACES_SAMPLER=$(az keyvault secret show --vault-name $AKV_NAME --name OTEL-TRACES-SAMPLER --query value -o tsv) \
    OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=$(az keyvault secret show --vault-name $AKV_NAME --name OTEL-INSTRUMENTATION-GENAI-CAPTURE-MESSAGE-CONTENT --query value -o tsv) \
  --assign-identity $USER_IDENTITY_ID \
  --dns-name-label ai-chat-$ACR_NAME \
  --os-type Linux \
  --cpu 1 \
  --memory 1.5 \
  --ports 80 \
  --query "{FQDN:ipAddress.fqdn}" \
  --output table  