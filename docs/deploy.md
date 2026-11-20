# Deploy

The backend runs in the dev environment of an AKS cluster from a Helm chart: `deploy/helm/knowledge-extractor`. This page says what is in it, what it expects from the cluster, where every setting goes and what is not there yet. How to install it, the first install, and the Azure side of the identity are in the chart's own [README](../deploy/helm/knowledge-extractor/README.md).

`make chart-check` lints the chart, renders it with the default values and with `values-dev.yaml`, and checks the output against the Kubernetes schemas (kubeconform, strict, Kubernetes 1.32). It also checks that the chart refuses to render without a secret source and without host names. It uses a local `helm` and `kubeconform` when there are any and their container images when not (nothing is installed on the machine). It is not part of `make check`.

## What the chart contains

In the table `<release>` stands for the release's full name: `<release>-knowledge-extractor`, or the release name alone when it already contains `knowledge-extractor`.

| Resource | Template | What it is |
| --- | --- | --- |
| Deployment `<release>-api` and Service `<release>-api` | `api-deployment.yaml`, `api-service.yaml` | The image's own command (uvicorn): HTTP and the WebSocket, port 8000. Start-up and liveness probe `/api/v1/health`, readiness `/api/v1/ready` (the database). The probes send the `Host` header (the first of `DJANGO_ALLOWED_HOSTS`, or `api.probeHost`) and `X-Forwarded-Proto: https`: without them the production settings answer 400 and 301 before the view runs, and readiness would not reach the database. |
| Deployment `<release>-worker` | `worker-deployment.yaml` | `python manage.py db_worker --no-reload` ([jobs.md](jobs.md)). No Service. The probe is compose's (the worker is process 1). Grace period 660 s: SIGTERM lets a running job finish (`EXECUTION_TIMEOUT_SECONDS` is 600). |
| Job `<release>-migrate` | `migrate-job.yaml` | `python manage.py migrate --noinput`, a Helm hook before every install and upgrade (after the install's resources with the dev PostgreSQL or Key Vault, see below). It reads the two hook copies below. |
| ConfigMap `<release>` | `configmap.yaml` | The settings that are not secret. `envFrom` in api and worker. An ordinary resource of the release. A change restarts api and worker (a checksum annotation). |
| Secret `<release>-secrets` | `secret.yaml` | Only when `secrets.existingSecret` is empty and Key Vault is off. An ordinary resource of the release. |
| ConfigMap `<release>-migrate`, Secret `<release>-migrate-secrets` | `configmap-migrate.yaml`, `secret-migrate.yaml` | The migration Job's own copies of the two above (the Secret only when the chart makes it), same data. Helm hooks, weight `-10`, removed when the Job succeeded. |
| ServiceAccount | `serviceaccount.yaml` | The identity of api and worker, with the Workload Identity annotations. |

The api, the worker and the migration share one image (`image.repository`, `image.tag`; the [Dockerfile](docker.md)). Pods run as user 999, non-root, no privilege escalation, all capabilities dropped, the default seccomp profile and a read-only root file system (`/tmp` is an `emptyDir`; the app writes nowhere else). Requests and limits and the replica counts are in `values.yaml`.

The ConfigMap and the chart-made Secret that api and worker read are ordinary release resources, so a failed migration, a rollback and `helm uninstall` behave as Helm usually does. The first install has none of them when the `pre-install` migration runs, and an upgrade must not change them before the migration succeeded, so the Job reads hook copies of its own (`<release>-migrate`, `<release>-migrate-secrets`). The chart's README has the consequences.

## What the chart expects from the cluster

- **Kubernetes 1.32 or later**, with the OIDC issuer and the Azure Workload Identity webhook enabled (`az aks update --enable-oidc-issuer --enable-workload-identity`) when `workloadIdentity.enabled`.
- **A namespace** and **an image** the nodes can pull (`imagePullSecrets`, or an ACR attached to the cluster). The chart builds nothing.
- **PostgreSQL**, reachable at `DATABASE_URL`, with the database and role created. **Redis** at `REDIS_URL` (the channel layer of the live updates). The chart brings its own for dev only (`postgres.enabled`, `redis.enabled`, below).
- For `keyVault.enabled`: the AKS add-on of the Secrets Store CSI driver with the Azure provider, which installs the `SecretProviderClass` CRD.
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

## Secrets from Key Vault

A placeholder, off until the vault exists (`keyVault.enabled: false`). When on, `secretproviderclass.yaml` renders a `SecretProviderClass` for the Azure provider of the Secrets Store CSI driver. It signs in with the workload identity of the chart's ServiceAccount (`clientID`, `tenantId`, `keyvaultName`) and `secretObjects` syncs the vault's secrets into the Kubernetes Secret the pods already read (`<release>-secrets`, or `keyVault.secretName`). With it, `secrets.existingSecret` is not needed and the chart makes no Secret of its own. The driver syncs a Secret only while a pod mounts the volume, so api, worker and the migration Job mount it (`/mnt/secrets-store`, read only); the Job runs as the chart's ServiceAccount and carries the `azure.workload.identity/use` label when the Key Vault is on.

What to create in Azure:

1. A Key Vault, with the Azure role-based access control model. Its name goes in `keyVault.keyvaultName`.
2. A secret for each of `DJANGO_SECRET_KEY`, `DATABASE_URL`, `REDIS_URL` and, with `ASSISTANT_AGENT=openai` and `LLM_PROVIDER=openai`, `OPENAI_API_KEY`. The names of the secrets in the vault go in `keyVault.objects.<VARIABLE>` (`values-dev.yaml` has placeholders). Only the objects the app needs are listed: `OPENAI_API_KEY` only in that combination.
3. The role **Key Vault Secrets User** on the vault (or on each secret) for the user-assigned managed identity of `workloadIdentity.clientId`. The federated credential for the ServiceAccount is the one of "Identity" in the chart's README.
4. In the cluster, the add-on: `az aks enable-addons --addons azure-keyvault-secrets-provider`.

In values: `keyVault.enabled: true`, `keyVault.keyvaultName`, the object names, and `workloadIdentity.enabled: true` with its client and tenant ids (`keyVault.clientId` and `keyVault.tenantId` override them). The chart refuses to render when one is missing, and when the driver's CRD is not in the cluster the install fails: that is why the file renders only when the feature is on. With Key Vault on, the vault's `DATABASE_URL` and `REDIS_URL` win over the dev PostgreSQL and Redis below.

The migration Job is a `post-install,pre-upgrade` hook with Key Vault on (the ServiceAccount does not exist before the install), see "Dev database and Redis".

A changed secret in the vault does not reach the pods by itself: environment variables are read at start. Either restart (`kubectl rollout restart deployment -l app.kubernetes.io/instance=<release>`), or enable the add-on's rotation (`--enable-secret-rotation`), which updates the mounted files and the synced Secret, and still needs a restart for the variables.

`make chart-check` renders the chart with `values-dev.yaml` and `keyVault.enabled=true`. The `SecretProviderClass` kind is skipped by kubeconform, because its schema belongs to the driver's CRD and is not in the Kubernetes schemas; every other resource, with the volume, is checked strictly.

## Dev database and Redis

For dev only: **no backups, one replica, no high availability.** `postgres.enabled` and `redis.enabled` (off in `values.yaml`, on in `values-dev.yaml`) add:

| Resource | Template | What it is |
| --- | --- | --- |
| StatefulSet, Service and Secret `<release>-postgres` | `postgres.yaml` | The official `postgres` image at the version of `compose.yaml` (18), a volume claim of `postgres.storage` (default `5Gi`, `postgres.storageClassName` or the cluster's default) at `/var/lib/postgresql`, user and database `ke`, start-up, readiness and liveness probes (`pg_isready`), requests and limits. Runs as user 999. |
| Deployment, Service and Secret `<release>-redis` | `redis.yaml` | The official `redis` image (8), password required, no snapshots and no persistence (an `emptyDir`), probes (`redis-cli ping`), requests and limits. |

The password of each: `postgres.password` or `redis.password` from values, or, when empty, **generated once on the first install and kept across upgrades**: the template reads the existing Secret with `lookup` and only draws a new random value when there is none. (`helm template` has no cluster, so it shows a fresh value each time; an install does not.) The PostgreSQL Secret has `helm.sh/resource-policy: keep`, so it outlives `helm uninstall` together with the volume claim, and a reinstall opens the old data with the old password. Passwords from values must be plain letters and digits: they go into a URL. Nothing has a non-empty default password.

When on, api, worker and migration get `DATABASE_URL` and `REDIS_URL` as environment entries built from the dependency's Secret (`postgres://ke:$(POSTGRES_PASSWORD)@<release>-postgres:5432/ke`, `redis://:$(REDIS_PASSWORD)@<release>-redis:6379/0`). An entry wins over the Secret's own value, so with `existingSecret` the Secret needs only `DJANGO_SECRET_KEY` (and `OPENAI_API_KEY`). Set the URL by hand in `secrets.values.DATABASE_URL` or `REDIS_URL` (or take it from Key Vault) and the chart leaves that one alone.

**Migration on a first install.** A `pre-install` hook runs before any resource of the release exists, so there would be no database to migrate. With `postgres.enabled` (or `keyVault.enabled`) the migration hooks run `post-install,pre-upgrade` instead: after the install created its resources, and still before every upgrade. The Job starts with an init container that waits (`pg_isready`) until the database answers. The api and worker pods of a first install may restart while the Job creates the tables. Without the dev PostgreSQL and Key Vault nothing changes: `pre-install,pre-upgrade`. With `helm --wait`, the install waits for pods that only become ready after the migration; use it without `--wait`, or on an upgrade.

## What is not there yet

- **An Ingress or Gateway**, and TLS: the Service is `ClusterIP`. Until then use `kubectl port-forward`.
- **The UI**: it has no image or chart yet.
- **A real Key Vault**: the chart has the placeholder (`keyVault`, off); the vault, the secrets and the roles are not created here.
- **A production-grade PostgreSQL and Redis**: the ones in the chart are for dev only.
- **A deployment or a pipeline**: nothing here deploys itself.
- **An autoscaler, network policies, a service mesh, a PodDisruptionBudget.**
- **The Azure resources**: the managed identity, the federated credential and the role assignments are described in the chart's README, not created.
- **Blob storage and an HTTP catalog** are settings only; the application still reads the samples.
