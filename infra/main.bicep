targetScope = 'subscription'

@minLength(1)
@maxLength(64)
@description('Name of the the environment which is used to generate a short unique hash used in all resources.')
param environmentName string

@minLength(1)
@description('Primary location for all resources & Flex Consumption Function App')
@allowed([
  'australiaeast'
  'australiasoutheast'
  'brazilsouth'
  'canadacentral'
  'centralindia'
  'centralus'
  'eastasia'
  'eastus'
  'eastus2'
  'eastus2euap'
  'francecentral'
  'germanywestcentral'
  'italynorth'
  'japaneast'
  'koreacentral'
  'northcentralus'
  'northeurope'
  'norwayeast'
  'southafricanorth'
  'southcentralus'
  'southeastasia'
  'southindia'
  'spaincentral'
  'swedencentral'
  'uaenorth'
  'uksouth'
  'ukwest'
  'westcentralus'
  'westeurope'
  'westus'
  'westus2'
  'westus3'
])
@metadata({
  azd: {
    type: 'location'
  }
})
param location string
param vnetEnabled bool
param apiServiceName string = ''
param apiUserAssignedIdentityName string = ''
param applicationInsightsName string = ''
param appServicePlanName string = ''
param logAnalyticsName string = ''
param resourceGroupName string = ''
param storageAccountName string = ''
param vNetName string = ''
@description('Id of the user identity to be used for testing and debugging. This is not required in production. Leave empty if not needed.')
param principalId string = ''

@description('GitHub Personal Access Token with Copilot Requests permission. Required for the Copilot SDK to authenticate and sign sessions.')
@secure()
@minLength(1)
param githubToken string

param aiFoundryName string = ''

@description('Model to use. GitHub models run via the Copilot SDK (no extra infra). Foundry models deploy a Microsoft Foundry account + model.')
@allowed([
  // GitHub Copilot models (no additional infrastructure needed)
  'github:claude-sonnet-4.6'
  'github:claude-opus-4.6'
  'github:gpt-5.2'
  'github:gpt-5.3-codex'
  // Microsoft Foundry models (deploys Foundry account + model)
  // 'foundry:gpt-4.1'
  // 'foundry:gpt-4.1-mini'
  // 'foundry:gpt-4.1-nano'
  // 'foundry:gpt-4o'
  // 'foundry:gpt-4o-mini'
  // 'foundry:gpt-5-mini'
  // 'foundry:gpt-5-nano'
  // 'foundry:gpt-5-chat'
  'foundry:gpt-5.1-codex-mini'
  // 'foundry:gpt-5.1-chat'
  // 'foundry:gpt-5.2-chat'
  // 'foundry:codex-mini'
  // 'foundry:o1'
  // 'foundry:o3-mini'
  // 'foundry:o4-mini'
  // 'foundry:claude-sonnet-4-5'
  // 'foundry:claude-opus-4-6'
  // 'foundry:claude-haiku-4-5'
])
param modelSelection string

// Parse the model selection prefix to determine deployment type
var isFoundryModel = startsWith(modelSelection, 'foundry:')
var isGitHubModel = startsWith(modelSelection, 'github:')
var deployFoundry = isFoundryModel
var selectedModelName = isFoundryModel ? substring(modelSelection, 8) : (isGitHubModel ? substring(modelSelection, 7) : modelSelection)

var abbrs = loadJsonContent('./abbreviations.json')
var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))
var tags = { 'azd-env-name': environmentName }
var functionAppName = !empty(apiServiceName) ? apiServiceName : '${abbrs.webSitesFunctions}api-${resourceToken}'
var deploymentStorageContainerName = 'app-package-${take(functionAppName, 32)}-${take(toLower(uniqueString(functionAppName, resourceToken)), 7)}'
var sessionShareName = 'code-assistant-session'

// Organize resources in a resource group
resource rg 'Microsoft.Resources/resourceGroups@2021-04-01' = {
  name: !empty(resourceGroupName) ? resourceGroupName : '${abbrs.resourcesResourceGroups}${environmentName}'
  location: location
  tags: tags
}

// User assigned managed identity to be used by the function app to reach storage and other dependencies
// Assign specific roles to this identity in the RBAC module
module apiUserAssignedIdentity 'br/public:avm/res/managed-identity/user-assigned-identity:0.4.1' = {
  name: 'apiUserAssignedIdentity'
  scope: rg
  params: {
    location: location
    tags: tags
    name: !empty(apiUserAssignedIdentityName) ? apiUserAssignedIdentityName : '${abbrs.managedIdentityUserAssignedIdentities}api-${resourceToken}'
  }
}

// Create an App Service Plan to group applications under the same payment plan and SKU
module appServicePlan 'br/public:avm/res/web/serverfarm:0.1.1' = {
  name: 'appserviceplan'
  scope: rg
  params: {
    name: !empty(appServicePlanName) ? appServicePlanName : '${abbrs.webServerFarms}${resourceToken}'
    sku: {
      name: 'FC1'
      tier: 'FlexConsumption'
    }
    reserved: true
    location: location
    tags: tags
  }
}

module api './app/api.bicep' = {
  name: 'api'
  scope: rg
  params: {
    name: functionAppName
    location: location
    tags: tags
    applicationInsightsName: monitoring.outputs.name
    appServicePlanId: appServicePlan.outputs.resourceId
    runtimeName: 'python'
    runtimeVersion: '3.12'
    storageAccountName: storage.outputs.name
    enableBlob: storageEndpointConfig.enableBlob
    enableQueue: storageEndpointConfig.enableQueue
    enableTable: storageEndpointConfig.enableTable
    enableFile: storageEndpointConfig.enableFiles
    deploymentStorageContainerName: deploymentStorageContainerName
    sessionShareName: sessionShareName
    identityId: apiUserAssignedIdentity.outputs.resourceId
    identityClientId: apiUserAssignedIdentity.outputs.clientId
    appSettings: union(
      {
        GITHUB_TOKEN: githubToken
        ENABLE_MULTIPLATFORM_BUILD: 'true'
        PYTHON_ENABLE_INIT_INDEXING: '1'
        AzureWebJobsDisableHomepage: 'true'
      },
      deployFoundry ? {
        AZURE_AI_FOUNDRY_ENDPOINT: foundryOpenAIEndpoint
        AZURE_AI_FOUNDRY_API_KEY: foundryApiKey
        AZURE_AI_FOUNDRY_MODEL: foundryModelDeployment
      } : {},
      isGitHubModel ? {
        COPILOT_MODEL: selectedModelName
      } : {}
    )
    virtualNetworkSubnetId: vnetEnabled ? serviceVirtualNetwork!.outputs.appSubnetID : ''
  }
}

// Backing storage for Azure functions backend API
module storage 'br/public:avm/res/storage/storage-account:0.8.3' = {
  name: 'storage'
  scope: rg
  params: {
    name: !empty(storageAccountName) ? storageAccountName : '${abbrs.storageStorageAccounts}${resourceToken}'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: true // Required for Azure Files SMB mount (session state persistence)
    dnsEndpointType: 'Standard'
    publicNetworkAccess: vnetEnabled ? 'Disabled' : 'Enabled'
    networkAcls: vnetEnabled ? {
      defaultAction: 'Deny'
      bypass: 'None'
    } : {
      defaultAction: 'Allow'
      bypass: 'AzureServices'
    }
    blobServices: {
      containers: [{name: deploymentStorageContainerName}]
    }
    fileServices: {
      shares: [{ name: sessionShareName, shareQuota: 1 }]
    }
    minimumTlsVersion: 'TLS1_2'  // Enforcing TLS 1.2 for better security
    location: location
    tags: tags
  }
}

// Define the configuration object locally to pass to the modules
var storageEndpointConfig = {
  enableBlob: true  // Required for AzureWebJobsStorage, .zip deployment, Event Hubs trigger and Timer trigger checkpointing
  enableQueue: false  // Required for Durable Functions and MCP trigger
  enableTable: false  // Required for Durable Functions and OpenAI triggers and bindings
  enableFiles: true    // Required for session state file share mount
  allowUserIdentityPrincipal: true   // Allow interactive user identity to access for testing and debugging
}

// Consolidated Role Assignments
module rbac './app/rbac.bicep' = {
  name: 'rbacAssignments'
  scope: rg
  params: {
    storageAccountName: storage.outputs.name
    appInsightsName: monitoring.outputs.name
    managedIdentityPrincipalId: apiUserAssignedIdentity.outputs.principalId
    userIdentityPrincipalId: principalId
    enableBlob: storageEndpointConfig.enableBlob
    enableQueue: storageEndpointConfig.enableQueue
    enableTable: storageEndpointConfig.enableTable
    allowUserIdentityPrincipal: storageEndpointConfig.allowUserIdentityPrincipal
  }
}

// Virtual Network & private endpoint to blob storage
module serviceVirtualNetwork './app/vnet.bicep' = if (vnetEnabled) {
  name: 'serviceVirtualNetwork'
  scope: rg
  params: {
    location: location
    tags: tags
    vNetName: !empty(vNetName) ? vNetName : '${abbrs.networkVirtualNetworks}${resourceToken}'
  }
}

module storagePrivateEndpoint './app/storage-PrivateEndpoint.bicep' = if (vnetEnabled) {
  name: 'servicePrivateEndpoint'
  scope: rg
  params: {
    location: location
    tags: tags
    virtualNetworkName: !empty(vNetName) ? vNetName : '${abbrs.networkVirtualNetworks}${resourceToken}'
    subnetName: vnetEnabled ? serviceVirtualNetwork!.outputs.peSubnetName : '' // Keep conditional check for safety, though module won't run if !vnetEnabled
    resourceName: storage.outputs.name
    enableBlob: storageEndpointConfig.enableBlob
    enableQueue: storageEndpointConfig.enableQueue
    enableTable: storageEndpointConfig.enableTable
    enableFile: storageEndpointConfig.enableFiles
  }
}

// Monitor application with Azure Monitor - Log Analytics and Application Insights
module logAnalytics 'br/public:avm/res/operational-insights/workspace:0.7.0' = {
  name: '${uniqueString(deployment().name, location)}-loganalytics'
  scope: rg
  params: {
    name: !empty(logAnalyticsName) ? logAnalyticsName : '${abbrs.operationalInsightsWorkspaces}${resourceToken}'
    location: location
    tags: tags
    dataRetention: 30
  }
}

module monitoring 'br/public:avm/res/insights/component:0.4.1' = {
  name: '${uniqueString(deployment().name, location)}-appinsights'
  scope: rg
  params: {
    name: !empty(applicationInsightsName) ? applicationInsightsName : '${abbrs.insightsComponents}${resourceToken}'
    location: location
    tags: tags
    workspaceResourceId: logAnalytics.outputs.resourceId
    disableLocalAuth: true
  }
}

// Microsoft Foundry account, project, and model deployment
module foundry './app/foundry.bicep' = if (deployFoundry) {
  name: 'foundry'
  scope: rg
  params: {
    aiFoundryName: !empty(aiFoundryName) ? aiFoundryName : '${abbrs.cognitiveServicesAccounts}${resourceToken}'
    tags: tags
    model: selectedModelName
  }
}

var foundryOpenAIEndpoint = foundry.?outputs.?aiFoundryOpenAIEndpoint ?? ''
var foundryApiKey = foundry.?outputs.?aiFoundryApiKey ?? ''
var foundryModelDeployment = foundry.?outputs.?modelDeploymentName ?? ''

// App outputs
output APPLICATIONINSIGHTS_CONNECTION_STRING string = monitoring.outputs.connectionString
output AZURE_LOCATION string = location
output AZURE_TENANT_ID string = tenant().tenantId
output SERVICE_API_NAME string = api.outputs.SERVICE_API_NAME
output AZURE_FUNCTION_NAME string = api.outputs.SERVICE_API_NAME
output AI_FOUNDRY_NAME string = foundry.?outputs.?aiFoundryName ?? ''
output AI_FOUNDRY_ENDPOINT string = foundry.?outputs.?aiFoundryEndpoint ?? ''
output AI_FOUNDRY_PROJECT_NAME string = foundry.?outputs.?aiProjectName ?? ''
output AI_FOUNDRY_MODEL_DEPLOYMENT_NAME string = foundryModelDeployment
