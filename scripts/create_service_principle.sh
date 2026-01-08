#!/bin/bash
set -e  # exit immediately if a command fails
#set -x  # print each command before executing it

# Initialize variables
RES_GROUP=""  #Fill out Your Resource Group
ACR_NAME=""   #Fill out Your ACR Name
AKV_NAME=$ACR_NAME-vault

az keyvault create --resource-group $RES_GROUP --name $AKV_NAME

ROLE=“AcrPull” 

az keyvault secret set \
  --vault-name $AKV_NAME \
  --name $ACR_NAME-pull-pwd \
  --value $(az ad sp create-for-rbac \
                --name $ACR_NAME-pull \
                --scopes $(az acr show --name $ACR_NAME --query id --output tsv) \
                --role "$ROLE" \
                --query password \
                --output tsv)

# Store service principal ID in AKV (the registry *username*)
az keyvault secret set --vault-name $AKV_NAME --name $ACR_NAME-pull-usr --value $(az ad sp list --display-name $ACR_NAME-pull --query [].appId --output tsv)