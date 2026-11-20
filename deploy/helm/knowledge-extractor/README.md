# knowledge-extractor chart

Runs the Knowledge Extractor API in a Kubernetes cluster (AKS, dev environment): the API, the background worker and the database migration. Templates only for now; nothing here deploys itself. What the chart contains, what it expects from the cluster and every setting: [docs/deploy.md](../../../docs/deploy.md).

## Install or upgrade

```sh
helm upgrade --install knowledge-extractor deploy/helm/knowledge-extractor \
  --namespace <namespace> --create-namespace \
  -f deploy/helm/knowledge-extractor/values-dev.yaml \
  --set image.tag=<tag> \
  --set secrets.existingSecret=<secret name>
```

Fill the placeholders in `values-dev.yaml` first (registry, host names, Entra ids, identity ids, Azure OpenAI). `make chart-check` lints and renders the chart without a cluster.

## Secrets

The pods read `DJANGO_SECRET_KEY`, `DATABASE_URL`, `REDIS_URL` (and `OPENAI_API_KEY` with `ASSISTANT_AGENT=openai` and `LLM_PROVIDER=openai`) from one Secret. The chart renders only when it has a source:

- `secrets.existingSecret=<name>`: a Secret that already exists in the namespace with those keys. The chart makes no Secret. This is where Azure Key Vault plugs in later (a synced Secret with that name).
- For a first try in dev: `secrets.values.<NAME>`, from which the chart makes the Secret. Pass them on the command line, never in a committed file: `--set-file secrets.values.DJANGO_SECRET_KEY=./key.txt --set secrets.values.DATABASE_URL=...`.

With neither, `helm template` and `helm install` stop with "No secret source: ...". A change to a chart-made Secret restarts the pods; after a change to an existing Secret run `kubectl rollout restart deployment -l app.kubernetes.io/instance=<release>`.

## Migration, and the first install

`<release>-migrate` is a Job and a Helm hook (`pre-install`, `pre-upgrade`): Helm runs it to completion before it creates or updates the Deployments, so a new version never serves traffic on an old schema, and a failed migration fails the `helm` command and leaves the running version in place. It runs `python manage.py migrate --noinput` (idempotent: it applies only what is missing), and is removed when it succeeds; a failed one stays for `kubectl logs job/<release>-migrate`.

On a first install the release has no resources yet, and a `pre-install` hook runs before they are created. The Job needs the settings and the Secret, so the ConfigMap and the chart-made Secret are hooks too, with a lower weight (`-10`): they are created first and are recreated before every upgrade, so the migration always sees the new values. The ServiceAccount is not a hook (a recreated one would invalidate the tokens of running pods), and the Job does not need it: it has no Azure identity and no API token. Consequences:

- With `secrets.existingSecret` the Secret must exist before the first install.
- The database named in `DATABASE_URL` and its role must exist (the chart ships no database); the migration creates the tables, including the job queue's.
- `helm uninstall` does not remove hook resources: delete the ConfigMap (named after the release: `<release>-knowledge-extractor`, or just the release name when it contains `knowledge-extractor`) and a chart-made Secret (`<name>-secrets`) by hand.

## Identity: Azure Workload Identity

The chart makes the ServiceAccount of the api and the worker. With `workloadIdentity.enabled` it annotates it (`azure.workload.identity/client-id`, and `tenant-id` when set) and labels the pods `azure.workload.identity/use: "true"`, so that Azure's webhook injects the federated token. `DefaultAzureCredential` in the app then signs in as the managed identity (Azure OpenAI today; blob storage and Key Vault next). The values in `values-dev.yaml` are placeholders (`00000000-...`).

The other half lives in Azure and is not created by this chart:

1. The cluster has the OIDC issuer and the workload identity webhook:

       az aks update -g <resource-group> -n <cluster> --enable-oidc-issuer --enable-workload-identity

2. A user-assigned managed identity. Its client id goes into `workloadIdentity.clientId`:

       az identity create -g <resource-group> -n <identity name>
       az identity show -g <resource-group> -n <identity name> --query clientId -o tsv

3. A federated credential that ties the ServiceAccount to it. The subject is `system:serviceaccount:<namespace>:<service account>`; `values-dev.yaml` fixes the service account name as `knowledge-extractor`:

       az identity federated-credential create \
         --name knowledge-extractor-dev \
         --identity-name <identity name> -g <resource-group> \
         --issuer "$(az aks show -g <resource-group> -n <cluster> --query oidcIssuerProfile.issuerUrl -o tsv)" \
         --subject system:serviceaccount:<namespace>:knowledge-extractor \
         --audiences api://AzureADTokenExchange

4. Roles for the identity, on the resources it uses:

   | Role | On | For |
   | --- | --- | --- |
   | Storage Blob Data Reader | the storage account | reading documents (`DOCUMENT_STORAGE=azure`, not built yet) |
   | Cognitive Services OpenAI User | the Azure OpenAI resource | the assistant (`LLM_PROVIDER=azure`) |
   | Key Vault Secrets User | the key vault | reading the secrets that become the Secret (the item after this one) |

## Read-only root file system

The containers run with `readOnlyRootFilesystem: true`, as user 999 without capabilities. The application writes nowhere but `/tmp` (an `emptyDir` is mounted there); this was checked by running the image read-only: the server, the worker and `migrate` all start and work. The one thing that would write elsewhere is the local dev token key (`AUTH_MODE=dev`), which production settings refuse.
