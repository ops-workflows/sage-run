{{/* Image reference for a component: dict "root" $ "component" "<name>". */}}
{{- define "sage-run.image" -}}
{{- $images := .root.Values.images -}}
{{- $override := index ($images.overrides | default dict) .component -}}
{{- if $override -}}
{{- $override -}}
{{- else -}}
{{- $tag := $images.tag | default .root.Chart.AppVersion -}}
{{- if $images.registry -}}{{- $images.registry -}}/{{- end -}}{{- $images.prefix -}}{{- .component -}}:{{- $tag -}}
{{- end -}}
{{- end -}}

{{- define "sage-run.serviceAccountName" -}}sage-run{{- end -}}

{{- define "sage-run.podDefaults" -}}
serviceAccountName: {{ include "sage-run.serviceAccountName" . }}
# Service-link variables (e.g. GATEWAY_PORT=tcp://...) collide with platform settings.
enableServiceLinks: false
{{- with .Values.hostAliases }}
hostAliases:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- with .Values.images.pullSecrets }}
imagePullSecrets:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- end -}}

{{/* Environment shared by platform workloads. Connection defaults (postgres,
     minio:9000, hindsight:8888, gateway:8080) match the in-namespace Service
     names, so only instance-specific values are set here. */}}
{{- define "sage-run.commonEnv" -}}
- name: PLATFORM_CONFIG_FILE
  value: /app/workflows/platform-config.yaml
- name: SAGE_RUN_ENV
  value: {{ .Values.environment | quote }}
- name: WORKFLOW_REPO_SOURCE
  value: {{ .Values.workflowRepo.source | quote }}
- name: WORKFLOW_REPO_URL
  value: {{ .Values.workflowRepo.url | quote }}
- name: WORKFLOW_REPO_REF
  value: {{ ternary "" .Values.workflowRepo.ref .Values.deployer.enabled | quote }}
- name: WORKFLOW_REPO_MANAGED
  value: {{ .Values.deployer.enabled | quote }}
- name: PG_DB
  value: {{ .Values.infrastructure.postgres.database | quote }}
- name: PG_USER
  value: {{ .Values.infrastructure.postgres.user | quote }}
- name: OBJECT_STORE_ACCESS_KEY
  value: {{ .Values.infrastructure.objectStore.accessKey | quote }}
- name: KNOWLEDGE_SOURCE_OBJECT_STORE_BUCKET
  value: {{ .Values.knowledgeSources.objectStoreBucket | quote }}
- name: RUNTIME_LAUNCHER
  value: kubernetes
- name: KUBERNETES_NAMESPACE
  valueFrom:
    fieldRef:
      fieldPath: metadata.namespace
{{- range $key, $value := .Values.env }}
- name: {{ $key }}
  value: {{ $value | quote }}
{{- end }}
{{- end -}}

{{- define "sage-run.bootstrapEnvFrom" -}}
- secretRef:
    name: {{ required "bootstrap.existingSecret is required" .Values.bootstrap.existingSecret }}
{{- end -}}

{{- define "sage-run.secretEnv" -}}
- name: {{ .name }}
  valueFrom:
    secretKeyRef:
      name: {{ required "bootstrap.existingSecret is required" .root.Values.bootstrap.existingSecret }}
      key: {{ .key }}
{{- end -}}

{{- define "sage-run.workflowRepoVolume" -}}
- name: workflow-repo
{{- if .Values.workflowRepo.hostPath }}
  hostPath:
    path: {{ .Values.workflowRepo.hostPath | quote }}
    type: Directory
{{- else }}
  persistentVolumeClaim:
    claimName: {{ required "workflowRepo.hostPath or workflowRepo.existingClaim is required" .Values.workflowRepo.existingClaim }}
{{- end }}
{{- end -}}

{{- define "sage-run.workflowRepoMount" -}}
- name: workflow-repo
  mountPath: /app/workflows
  readOnly: {{ not .writable }}
{{- end -}}

{{- define "sage-run.storageClass" -}}
{{- with .Values.infrastructure.storageClass }}
storageClassName: {{ . | quote }}
{{- end }}
{{- end -}}

{{/* Extra env for one workload: dict "root" $ "name" "<deployment name>". */}}
{{- define "sage-run.serviceEnv" -}}
{{- range $key, $value := index (.root.Values.serviceEnv | default dict) .name | default dict }}
- name: {{ $key }}
  value: {{ $value | quote }}
{{- end }}
{{- end -}}
