# AI Control Plane

**Priority-aware model routing • Kubernetes infrastructure • Financial observability**

A Kubernetes-oriented prototype for **decoupling the application layer from model-selection policy**. A Flask router selects a model from request priority and prompt length, simulates inference, and exposes cost savings through Prometheus metrics.

- **Routing policy:** Direct eligible low-priority requests to a lightweight model.
- **Resource efficiency:** Demonstrate a routing strategy aimed at **preventing resource contention**; GPU scheduling and workload isolation are not implemented.
- **Financial observability:** Track cumulative **simulated savings** alongside simulated GPU utilization.

**Current scope:** Runnable router, container image, Kubernetes manifests, custom resource schema, Prometheus scrape configuration, and CI tests. Inference backends and a custom resource controller are not implemented.

---

## System Architecture

```text
Client application
    |
    | POST /v1/chat/completions + X-Priority
    v
Flask router (Kubernetes Deployment + ClusterIP Service)
    |
    +-- Low priority + prompt < 50 characters --> qwen-2.5-0.5b
    +-- All other valid requests -------------> llama-3.2-1b
    |                                          (model selection only)
    v
Simulated response + cost accounting
    |
    v
/metrics <---- Prometheus scrape configuration
    ^
    |
Background GPU-utilization simulator
```

**Client Request Lifecycle — Lightweight Path**

1. **Client request** ➔ Submit a JSON `prompt` to `/v1/chat/completions`.
2. **Priority classification** ➔ Read `X-Priority: Low` and check that the prompt is shorter than 50 characters.
3. **Router** ➔ Apply the model-selection policy within the Flask endpoint.
4. **Low priority (lightweight model)** ➔ Select `qwen-2.5-0.5b`.
5. **Simulated inference** ➔ Prepare a routing response with `simulated: true`; no model executes.
6. **Cost savings recorded** ➔ Assign **$0.04 in simulated savings** to the request.
7. **Prometheus metrics updated** ➔ Increment the savings counter, available on the next `/metrics` scrape.

**Infrastructure extension:** The `InferenceDeployment` CRD defines model intent. The Karpenter NodePool blueprint describes GPU capacity. Neither is connected to the router by a controller.

---

## Quick Start

**Prerequisite:** Python **3.12+**. Run from the repository root.

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -r control-plane/requirements.txt
python control-plane/router.py
```

**Send a request from another terminal:**

```sh
curl -s http://localhost:5000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H 'X-Priority: Low' \
  -d '{"prompt":"Explain Kubernetes briefly."}'
curl -s http://localhost:5000/metrics
```

**Expected response:**

```json
{"model":"qwen-2.5-0.5b","cost_saved_usd":0.04,"simulated":true}
```

### Routing Contract

| **Condition** | **Selected model** | **Simulated savings** |
| --- | --- | --- |
| Exactly `X-Priority: Low` and prompt length **< 50 characters** | `qwen-2.5-0.5b` | **$0.04/request** |
| All other valid requests | `llama-3.2-1b` | **$0.00/request** |

**Validation:** The body must be a JSON object containing a string `prompt`. Invalid JSON or a missing/non-string prompt returns **HTTP 400**.

### Financial Observability

| **Metric** | **Behavior** |
| --- | --- |
| `ai_platform_cost_saved_usd_total` | Cumulative simulated savings from lightweight routing. |
| `ai_platform_gpu_utilization_percentage` | Simulated utilization between **65–90%**, initialized at startup and updated every **5 seconds** when running `router.py`. |

**Metrics are in memory** and reset on process restart. Scraping reads current values without changing GPU state. `telemetry/prometheus.yaml` targets `model-router:5000`; Prometheus must run where that Service resolves. A Prometheus deployment and Grafana dashboards are not included.

---

## Deploy to kind

**Prerequisites:** Docker running, `kubectl`, and an existing kind cluster named **`kind`**. For another cluster name, update both `--name` and the `kind-<name>` context.

```sh
docker build -t model-router:local .
kind load docker-image model-router:local --name kind
kubectl --context kind-kind apply \
  -f k8s/manifests/router-deployment.yaml \
  -f k8s/manifests/router-service.yaml
kubectl --context kind-kind rollout status deployment/model-router --timeout=120s
kubectl --context kind-kind port-forward service/model-router 5000:5000
```

**Access:** Use the quick-start requests while port-forwarding is active. The ClusterIP Service exposes **port 5000**. This local demo runs **one replica** of the Flask development server and uses `imagePullPolicy: IfNotPresent` for the loaded image.

**After rebuilding and reloading the same image tag:**

```sh
kubectl --context kind-kind rollout restart deployment/model-router
kubectl --context kind-kind rollout status deployment/model-router --timeout=120s
```

---

## InferenceDeployment API

**Install the schema and sample resource into your current Kubernetes context:**

```sh
kubectl apply -f k8s/crds/inference-crd.yaml
kubectl wait --for=condition=Established crd/inferencedeployments.ai.platform.io --timeout=60s
kubectl apply -f k8s/custom-resources/example-deployment.yaml
```

The namespaced **`ai.platform.io/v1alpha1`** API requires:

| **Spec field** | **Contract** | **Example** |
| --- | --- | --- |
| `modelName` | Model name as a string | `llama-3.2-1b` |
| `priority` | `High`, `Low`, or `Batch` | `High` |
| `maxLatencyMs` | Requested maximum latency as an integer, in milliseconds | `800` |

**Schema only:** Creating a resource does not launch a model or enforce priority or latency. The separate Karpenter blueprint requires an AWS Karpenter installation and a GPU-compatible `EC2NodeClass` named `gpu`.

---

## Teardown

Run these commands from the repository root. Stop the local router and any
`kubectl port-forward` process with **Ctrl+C** in their terminals.

Remove the router from the kind cluster:

```sh
kubectl --context kind-kind delete --ignore-not-found \
  -f k8s/manifests/router-deployment.yaml \
  -f k8s/manifests/router-service.yaml
```

Use the same namespace as the deployment if you changed the context's default
namespace. For a differently named kind cluster, replace `kind-kind` with its
context name.

If you installed the sample `InferenceDeployment`, remove it from the context
and namespace where you installed it. The commands below assume `kind-kind`:

```sh
kubectl --context kind-kind delete --ignore-not-found \
  -f k8s/custom-resources/example-deployment.yaml
```

Optionally remove the CRD when no other workloads need it. **Deleting the CRD
also deletes all `InferenceDeployment` resources in every namespace in that
cluster.** Inspect them first:

```sh
kubectl --context kind-kind get inferencedeployments.ai.platform.io --all-namespaces
kubectl --context kind-kind delete --ignore-not-found -f k8s/crds/inference-crd.yaml
```

Optionally remove the host's demo image:

```sh
docker image rm model-router:local
```

If the entire kind cluster is disposable, delete it instead of removing
individual Kubernetes resources. **This removes every workload in that cluster**,
including images loaded into its nodes:

```sh
kind delete cluster --name kind
```

The kind walkthrough does not install the AWS Karpenter blueprint. If you applied
it separately, manage its teardown in that AWS cluster after reviewing the GPU
workloads and provisioned nodes; the commands above do not clean up AWS resources.

---

## Repository Structure

```text
├── .github/workflows/ci.yml       # Python syntax checks and router tests
├── control-plane/                # Flask routing policy, metrics, and tests
├── Dockerfile                    # Python 3.12 router image
├── k8s/
│   ├── manifests/                # Router Deployment/Service; Karpenter blueprint
│   ├── crds/                     # InferenceDeployment schema
│   └── custom-resources/         # Sample model intent
└── telemetry/prometheus.yaml     # Router scrape configuration
```

---

## Validation

**With dependencies installed and the virtual environment active:**

```sh
python -m compileall -q control-plane
python -m unittest discover -s control-plane -p 'test_*.py'
```

**CI runs both checks on pushes and pull requests.** Tests cover routing boundaries, input validation, cumulative savings, and GPU simulator behavior.

## License

This project is licensed under the [MIT License](LICENSE).

Copyright (c) 2026 Mohamed A. Mohamed.

Author: Mohamed Mohamed

Email: mohamed0395@gmail.com
