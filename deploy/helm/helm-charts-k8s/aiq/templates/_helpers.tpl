{{/*
Expand the name of the chart.
*/}}
{{- define "aiq.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "aiq.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "aiq.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "aiq.labels" -}}
helm.sh/chart: {{ include "aiq.chart" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
project: {{ .Values.project.name }}
{{- with .Values.project.deploymentEnv }}
environment: {{ . }}
{{- end }}
{{- if ne (.Values.project.orientation | default "internal") "external" }}
{{- with .Values.project.dl }}
dl: {{ . }}
{{- end }}
{{- with .Values.project.nspect_id }}
nspect_id: {{ . }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Generate namespace name
*/}}
{{- define "aiq.namespace" -}}
{{- if eq (.Values.project.deploymentTarget | default "") "kind" -}}
{{- .Values.appname -}}
{{- else -}}
{{- printf "ns-%s" .Values.appname -}}
{{- end -}}
{{- end }}

{{/*
Generate app-specific name
*/}}
{{- define "aiq.appName" -}}
{{- $global := index . 0 -}}
{{- $appName := index . 1 -}}
{{- printf "%s-%s" $global.Values.project.name $appName | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Generate app-specific fullname (with truncation)
*/}}
{{- define "aiq.appFullname" -}}
{{- $global := index . 0 -}}
{{- $appName := index . 1 -}}
{{- printf "%s-%s" $global.Values.project.name ($appName | trunc 15 | trimSuffix "-") | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Generate app-specific labels
*/}}
{{- define "aiq.appLabels" -}}
{{- $global := index . 0 -}}
{{- $appName := index . 1 -}}
{{- $appConfig := index . 2 -}}
{{ include "aiq.labels" $global }}
app: {{ include "aiq.appName" (list $global $appName) }}
{{- with $appConfig.labels }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{/*
Generate app-specific selector labels
*/}}
{{- define "aiq.appSelectorLabels" -}}
{{- $global := index . 0 -}}
{{- $appName := index . 1 -}}
app: {{ include "aiq.appName" (list $global $appName) }}
{{- end }}

{{/*
Get component name (auto-derive from app name if not specified)
*/}}
{{- define "aiq.component" -}}
{{- $appName := index . 0 -}}
{{- $appConfig := index . 1 -}}
{{- $appConfig.component | default $appName -}}
{{- end }}

{{/*
Get image repository (use global, appDefaults, or app-specific)
*/}}
{{- define "aiq.imageRepository" -}}
{{- $global := index . 0 -}}
{{- $appConfig := index . 1 -}}
{{- $defaults := $global.Values.appDefaults | default dict -}}
{{- $defaultImage := $defaults.image | default dict -}}
{{- $appImage := $appConfig.image | default dict -}}
{{- if $appImage.repository -}}
{{- $appImage.repository -}}
{{- else if $global.Values.imageRepository -}}
{{- $global.Values.imageRepository -}}
{{- else if $defaultImage.repository -}}
{{- $defaultImage.repository -}}
{{- else -}}
{{- fail "image.repository is required. Set it globally via imageRepository, in appDefaults.image.repository, or per app" -}}
{{- end -}}
{{- end }}

{{/*
Extract base name for auto-generating image names
Uses project.name as the base for image names (e.g., "test-francis-z-2")
This ensures image names match the project naming convention
*/}}
{{- define "aiq.imageBaseName" -}}
{{- $global := index . 0 -}}
{{- $appConfig := index . 1 -}}
{{- $global.Values.project.name -}}
{{- end }}

{{/*
Get image name (auto-generate from imageRepository base + app if not specified)
*/}}
{{- define "aiq.imageName" -}}
{{- $global := index . 0 -}}
{{- $appName := index . 1 -}}
{{- $appConfig := index . 2 -}}
{{- $appImage := $appConfig.image | default dict -}}
{{- if $appImage.name -}}
{{- $appImage.name -}}
{{- else -}}
{{- $baseName := include "aiq.imageBaseName" (list $global $appConfig) -}}
{{- printf "%s-%s" $baseName $appName -}}
{{- end -}}
{{- end }}

{{/*
Auto-generate DataDog labels from project metadata (no-op if customerID not set)
*/}}
{{- define "aiq.datadogLabels" -}}
{{- end }}

{{/*
Get app port (from port or ports[0].containerPort)
*/}}
{{- define "aiq.appPort" -}}
{{- $appConfig := index . 0 -}}
{{- if hasKey $appConfig "port" -}}
{{- $appConfig.port -}}
{{- else if hasKey $appConfig "ports" -}}
{{- if $appConfig.ports -}}
{{- (index $appConfig.ports 0).containerPort -}}
{{- else -}}
{{- fail "Either 'port' or 'ports' must be specified for the app" -}}
{{- end -}}
{{- else -}}
{{- fail "Either 'port' or 'ports' must be specified for the app" -}}
{{- end -}}
{{- end }}

{{/*
Auto-generate ingress hostname
Uses base name from imageRepository instead of full project name for consistency
*/}}
{{- define "aiq.ingressHostname" -}}
{{- $global := index . 0 -}}
{{- $appName := index . 1 -}}
{{- $appConfig := index . 2 -}}
{{- $appIngress := $appConfig.ingress | default dict -}}
{{- $baseName := include "aiq.imageBaseName" (list $global $appConfig) -}}
{{- if eq (kindOf $appIngress) "map" -}}
{{- if $appIngress.hostname -}}
{{- $appIngress.hostname -}}
{{- else -}}
{{- printf "%s-%s.local" $baseName $appName -}}
{{- end -}}
{{- else -}}
{{- printf "%s-%s.local" $baseName $appName -}}
{{- end -}}
{{- end }}

{{/*
Merge app config with defaults
Usage: include "aiq.mergeAppDefaults" (list $ $appName $appConfig)
Returns: merged config with defaults applied
*/}}
{{- define "aiq.mergeAppDefaults" -}}
{{- $global := index . 0 -}}
{{- $appName := index . 1 -}}
{{- $appConfig := index . 2 -}}
{{- $merged := deepCopy $global.Values.appDefaults | mustMerge (deepCopy $appConfig) -}}
{{- $merged | toJson -}}
{{- end }}

{{/*
Get app config value with default fallback
Usage: include "aiq.appValue" (dict "global" $ "app" $appConfig "path" "image.pullPolicy" "default" "IfNotPresent")
*/}}
{{- define "aiq.appValue" -}}
{{- $global := .global -}}
{{- $app := .app -}}
{{- $path := .path -}}
{{- $default := .default -}}
{{- $pathParts := splitList "." $path -}}
{{- $appValue := $app -}}
{{- $defaultValue := $global.Values.appDefaults -}}
{{- $foundApp := true -}}
{{- $foundDefault := true -}}
{{- range $pathParts -}}
  {{- if and $foundApp (hasKey $appValue .) -}}
    {{- $appValue = index $appValue . -}}
  {{- else -}}
    {{- $foundApp = false -}}
  {{- end -}}
  {{- if and $foundDefault (hasKey $defaultValue .) -}}
    {{- $defaultValue = index $defaultValue . -}}
  {{- else -}}
    {{- $foundDefault = false -}}
  {{- end -}}
{{- end -}}
{{- if $foundApp -}}
  {{- $appValue -}}
{{- else if $foundDefault -}}
  {{- $defaultValue -}}
{{- else -}}
  {{- $default -}}
{{- end -}}
{{- end }}
