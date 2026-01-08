#!/bin/bash
set -e  # exit immediately if a command fails
#set -x  # print each command before executing it

# Initialize variables
RES_GROUP=""  #Fill out Your Resource Group
ACR_NAME=""   #Fill out Your ACR Name

# Login to Azure Container Registry
az acr login --name "$ACR_NAME"

# Build from ../src (where Dockerfile + source live)
docker buildx build \
  --platform linux/amd64 \
  -t "$ACR_NAME.azurecr.io/$ACR_NAME:latest" \
  -f ../src/Dockerfile \
  ../src

# Push image to ACR
docker push "$ACR_NAME.azurecr.io/$ACR_NAME:latest"