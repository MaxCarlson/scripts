# H4 WDDM Process Attribution

Date: 2026-11-14 (Pacific)
GPU observed: RTX 5090, UUID `GPU-d573e046-ec53-77d8-009b-93c6e6bc60b6`; driver/NVML `621.14`.

## Read-only probe

`tools/h4_qualification/wddm_probe.py` performs bounded NVML v3 compute and graphics process queries for an explicit GPU UUID. It captures at most six snapshots, bounds the vendor call in a helper process, resolves each returned PID through `psutil` to creation time and executable path, and correlates a supplied expected PID only when creation-time and executable identity match. It never calls a GPU setter. The JSON keeps the WDDM unavailable-memory sentinel separate from process presence and labels API errors instead of turning them into empty inventories.

The `nvmlProcessInfo_t` v3 structure used by this probe has the documented fields `pid`, `usedGpuMemory`, `gpuInstanceId`, and `computeInstanceId`. On this host the v3 calls returned stable row counts and the expected PID was correlated with an independently inspected Windows process identity. This validates the exercised ABI and correlation for these calls on the observed driver; it does not establish global inventory completeness or qualify every driver/API version.

## Observed samples

The final probe sampled at approximately 2026-11-14 23:25:28, 23:25:30, and 23:25:32 Pacific, using the then-current read-only Coordinator status identity for its owned miner. All three samples had:

- Requested/observed GPU UUID match and driver `621.14`.
- Each sample reported the same GPU UUID and driver as the first sample (`same_device_identity`).
- Compute API status `available`, 41 rows; graphics API status `available`, 39 rows.
- All 41 union process rows had independently readable PID, creation time, and executable identity in that sample.
- The Coordinator-reported KRig process appeared in the **compute** query in all three samples with matching PID, creation time, and exact executable path. It did not appear in the graphics-query rows.
- Its WDDM `usedGpuMemory` was `NVML_VALUE_NOT_AVAILABLE`; this is a memory-field limitation and does not mean the process row was absent.

The probe output was kept under the module-local ignored `.pytest_tmp_root/h4-wddm-probe-20261114/` directory. It contains volatile host PID/path details and is not committed. The durable report records only bounded counts and identity-match classifications.

## Capability matrix

| Evidence source | Coverage / identity | Permissions and limitations | Authority |
|---|---|---|---|
| NVML compute-running-process v3 | Compute contexts; observed PID list on the selected GPU | Dynamic enumeration; may return unsupported, permission, GPU-lost, or size-race errors. A successful sample is not a completeness guarantee. | Diagnostic process evidence only. |
| NVML graphics-running-process v3 | Graphics contexts; separate from compute enumeration | Same dynamic/permission limits; KRig was absent from this API in these samples. | Diagnostic process evidence only. |
| NVML `usedGpuMemory` | Per-row memory where available | NVIDIA documents this as unavailable under WDDM; `[N/A]` cannot be treated as process absence. | Not termination evidence. |
| Windows `psutil` process inspection | PID, exact create time, executable path for sampled PIDs | Requires permission; races with exit/reuse; does not independently prove which GPU contexts the process owns. | Strong PID identity correlation, not inventory completeness. |
| RC status | Managed-miner ownership claim and PID/create-time identity | Reports Coordinator state; must still be cross-checked with OS process identity. | Authoritative for RC's own recorded ownership, not global GPU use. |
| `nvidia-smi --query-compute-apps` | Compute-process rows only | Empty or incomplete output is not proof no graphics or other GPU process exists. | Diagnostic only. |
| GPUView / ETW DxgKrnl | Potential Windows GPU scheduling/context traces | Requires elevated tracing and can produce large ETL evidence; not run in this assignment. Scope/completeness must be independently qualified. | Not qualified here. |

NVIDIA documents compute and graphics queries separately and documents WDDM `usedGpuMemory` unavailability. See [NVML device query APIs](https://docs.nvidia.com/deploy/nvml-api/latest/api/group__nvmlDeviceQueries.html) and [nvmlProcessInfo_t](https://docs.nvidia.com/deploy/nvml-api/latest/api/structnvmlProcessInfo__t.html). Microsoft documents GPUView as an ETW/DxgKrnl-based diagnostic tool; no elevated trace was started. See [Using GPUView](https://learn.microsoft.com/en-us/windows-hardware/drivers/display/using-gpuview).

## Disposition

The known managed miner is repeatedly visible in the compute process list and its identity matches Windows process inspection. That is useful corroborating evidence for this process, but it is not a proof that every relevant WDDM process or execution boundary is enumerated. Keep `gpu_process_attribution_confirmed=false`. Do not enable Case C termination recovery or unattended recovery on this evidence. A complete attribution method must demonstrate coverage across known harmless graphics and compute workloads, permission errors, process races, adapter identity, and all relevant execution boundaries.
