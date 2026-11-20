# Deploy

The backend runs in the dev environment of an AKS cluster from a Helm chart: `deploy/helm/knowledge-extractor`. This page says what is in it, what it expects from the cluster, where every setting goes and what is not there yet. How to install it, the first install, and the Azure side of the identity are in the chart's own [README](../deploy/helm/knowledge-extractor/README.md).

`make chart-check` lints the chart, renders it with the default values and with `values-dev.yaml`, and checks the output against the Kubernetes schemas (kubeconform, strict, Kubernetes 1.32). It also checks that the chart refuses to render without a secret source and without host names. It uses a local `helm` and `kubeconform` when there are any and their container images when not (nothing is installed on the machine). It is not part of `make check`.

## What the chart contains

In the table `<release>` stands for the release's full name: `<release>-knowledge-extractor`, or the release name alone when it already contains `knowledge-extractor`.

| Resource | Template | What it is |
| --- | --- | --- |
| Deployment `<release>-api` and Service `<release>-api` | `api-deployment.yaml`, `api-service.yaml` | The image's own command (uvicorn): HTTP and the WebSocket, port 8000. Start-up and liveness probe `/api/v1/health`, readiness `/api/v1/ready` (the database). The probes send the `Host` header (the first of `DJANGO_ALLOWED_HOSTS`, or `api.probeHost`) and `X-Forwarded-Proto: https`: without them the production settings answer 400 and 301 before the view runs, and readiness would not reach the database. |
| Deployment `<release>-worker` | `worker-deployment.yaml` | `python manage.py db_worker --no-reload` ([jobs.md](jobs.md)). No Service. The probe is compose's (the worker is process 1). Grace period 660 s: SIGTERM lets a running job finish (`EXECUTION_TIMEOUT_SECONDS` is 600). |
| Job `<release>-migrate` | `migrate-job.yaml` | `python manage.py migrate --noinput`, a Helm hook before every install and upgrade. |
| ConfigMap `<release>` | `configmap.yaml` | The settings that are not secret. `envFrom` in all three pods. A change restarts api and worker (a checksum annotation). |
| Secret `<release>-secrets` | `secret.yaml` | Only when `secrets.existingSecret` is empty. |
| ServiceAccount | `serviceaccount.yaml` | The identity of api and worker, with the Workload Identity annotations. |

The api, the worker and the migration share one image (`image.repository`, `image.tag`; the [Dockerfile](docker.md)). Pods run as user 999, non-root, no privilege escalation, all capabilities dropped, the default seccomp profile and a read-only root file system (`/tmp` is an `emptyDir`; the app writes nowhere else). Requests and limits and the replica counts are in `values.yaml`.

The ConfigMap and the chart-made Secret are Helm hooks (`pre-install`, `pre-upgrade`, weight `-10`) so that the migration Job, which runs before the release's other resources exist, can read them. The chart's README explains why and what follows (they are not removed by `helm uninstall`).

## What the chart expects from the cluster

- **Kubernetes 1.32 or later**, with the OIDC issuer and the Azure Workload Identity webhook enabled (`az aks update --enable-oidc-issuer --enable-workload-identity`) when `workloadIdentity.enabled`.
- **A namespace** and **an image** the nodes can pull (`imagePullSecrets`, or an ACR attached to the cluster). The chart builds nothing.
- **PostgreSQL**, reachable at `DATABASE_URL`, with the database and role created. **Redis** at `REDIS_URL` (the channel layer of the live updates). The chart ships neither.
- **A Secret** with the secret settings, or the values to make one (below).
- For telemetry: **an OpenTelemetry collector** in the cluster, whose OTLP/HTTP address is `OTEL_EXPORTER_OTLP_ENDPOINT`. Telemetry is off until `OTEL_SDK_DISABLED` is `false`.
- **TLS in front.** The production settings redirect to HTTPS and trust `X-Forwarded-Proto`; the ingress (not in the chart yet) must send it.

## Settings

Every variable of `.env.example` that the production settings read is in one of these places, or is left out on purpose below. The ConfigMap keys are the `config:` map of `values.yaml`; add a key there to add a setting.

| Variable | Where | Why |
| --- | --- | --- |
| `DJANGO_SETTINGS_MODULE` | ConfigMap | `config.settings.production` (the image's default, set explicitly) |
| `DJANGO_ALLOWED_HOSTS`, `DJANGO_SECURE_SSL_REDIRECT`, `CORS_ALLOWED_ORIGINS` | ConfigMap | host names and origins are public configuration |
| `AUTH_MODE`, `ENTRA_TENANT_ID`, `ENTRA_CLIENT_ID`, `ENTRA_REQUIRED_SCOPE` | ConfigMap | `entra` in the cluster (dev is refused); the ids identify the app registration and are not secret |
| `LOG_LEVEL`, `LOG_FORMAT`, `API_DOCS_ENABLED`, `WS_TICKET_TTL_SECONDS` | ConfigMap | behaviour |
| `DOCUMENT_CATALOG`, `DOCUMENT_CATALOG_URL`, `DOCUMENT_STORAGE`, `AZURE_STORAGE_ACCOUNT_URL` | ConfigMap | choices and addresses. Access to the account is the managed identity, not a key |
| `ASSISTANT_AGENT`, `ASSISTANT_REPLY_TIMEOUT_SECONDS`, `EXTRACTOR`, `EXECUTION_TIMEOUT_SECONDS` | ConfigMap | behaviour and timeouts |
| `LLM_PROVIDER`, `LLM_MODEL`, `AZURE_OPENAI_ENDPOINT` | ConfigMap | `azure` signs in with the managed identity: no key |
| `OTEL_SDK_DISABLED`, `OTEL_SERVICE_NAME`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_RESOURCE_ATTRIBUTES`, `OTEL_LOGS_EXPORTER` | ConfigMap | telemetry, off by default. The worker's service name is set by the chart (`worker.otelServiceName`) |
| `DJANGO_SECRET_KEY` | Secret | signs sessions |
| `DATABASE_URL` | Secret | holds the database password |
| `REDIS_URL` | Secret | may hold a password |
| `OPENAI_API_KEY` | Secret, only with `ASSISTANT_AGENT=openai` and `LLM_PROVIDER=openai` | the key. Without that combination nothing reads it |
| `DJANGO_DEBUG` | left out | production is always off |
| `DEV_AUTH_KEY_PATH` | left out | `AUTH_MODE=dev` only, which production refuses |
| `DB_PORT`, `REDIS_PORT` | left out | host ports of the compose services; they only build the local default URLs, and the chart gives both URLs |
| `REALTIME_TEST_ROUTE` | left out | the echo socket must stay off; the default is off |
| `OTEL_GRPC_PORT`, `OTEL_HTTP_PORT`, `SPLUNK_ACCESS_TOKEN`, `SPLUNK_REALM`, `SPLUNK_HEC_URL`, `SPLUNK_HEC_TOKEN`, `SPLUNK_INDEX`, `SPLUNK_SOURCETYPE`, `SPLUNK_HEC_INSECURE_SKIP_VERIFY` | left out | settings of the collector, not of the app; this chart ships no collector |

The secret settings come from `secrets.existingSecret` (the name of a Secret with those keys; the chart makes none) or, for a first try in dev, from `secrets.values.*` (empty in every committed file; the chart makes the Secret). The chart refuses to render with neither (`No secret source: ...`), and when `DJANGO_ALLOWED_HOSTS` is empty or `workloadIdentity` is enabled without a client id.

Endpoints and ids in `values-dev.yaml` are placeholders (`replace-me`, `00000000-...`); fill them in before deploying. The values of the Azure side are described in the chart's README.

## What is not there yet

- **An Ingress or Gateway**, and TLS: the Service is `ClusterIP`. Until then use `kubectl port-forward`.
- **The UI**: it has no image or chart yet.
- **Azure Key Vault**: the Secret is expected to exist (`secrets.existingSecret`); filling it from Key Vault is the next item.
- **PostgreSQL and Redis in the cluster.**
- **A deployment or a pipeline**: nothing here deploys itself.
- **An autoscaler, network policies, a service mesh, a PodDisruptionBudget.**
- **The Azure resources**: the managed identity, the federated credential and the role assignments are described in the chart's README, not created.
- **Blob storage and an HTTP catalog** are settings only; the application still reads the samples.
