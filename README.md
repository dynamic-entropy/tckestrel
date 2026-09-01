# tckestrel

Fleet controller for [xrdhover](https://github.com/dynamic-entropy/xrdhover) WAN-hold jobs on HTCondor.

A matrix cell `(source, dest)` means: land the job at dest (`+DESIRED_Sites`) and read pinned `root://` PFNs at source. That is the WAN link being held.

The job executable is `run_xrdhover.sh`. It sources CMS `cmsset_default.sh`, cmsenv of `cmssw` (default `CMSSW_20_1_0_pre2`), then execs the transferred `xrdhover`. That release ships XRootD 6.0.2 (`libXrdCl.so.6`) on el9, which matches `required_os: rhel9`. The fetched `linux-amd64` binary is itself an AlmaLinux 9 build — do not cache an el10 tarball under that name.

Managed with [uv](https://docs.astral.sh/uv/).

## Install

```sh
uv sync --group dev
```

Runtime dependency: PyYAML.

Development extras: pytest, `rucio-clients`, `htcondor` (`htcondor2` bindings).

A production install (`uv sync`) uses the site Rucio and HTCondor. Source the CMS Rucio setup before resolve or submit:

```sh
source /cvmfs/cms.cern.ch/rucio/setup.sh
```

Rucio and HTCondor are imported when the corresponding command runs.

YAML paths (`matrix`, `filelists_dir`, `site_map`, `xrdhover`, `xrdhover_dir`) are resolved relative to the config file, then the current working directory. `$HOME` and `~` are expanded.

## CLI

```text
tckestrel COMMAND -c/--config YAML
```

| Command | What it does |
|---|---|
| `plan` | Print cells, `N`, job rate, sidecar counts |
| `payload` | Fetch xrdhover into `$HOME/vendor/xrdhover/<version>/linux-amd64/` |
| `resolve` | Stamp planned LFNs with pinned `root://` PFNs (rejects AAA) |
| `render` | Write `job.json` + `files.txt` for every planned cell |
| `submit` | Resolve, render, write `job.sub`, queue N jobs per cell |
| `jobs` | Query the campaign on the schedd |
| `rm` | `condor_rm` the campaign |

`submit` already resolves and renders. `resolve` / `render` are preflight. The matrix selects cells.

| Flag | Commands | Notes |
|---|---|---|
| `--dry-run` | submit | Write files; do not contact the schedd |
| `--validate` | render, submit | `xrdhover validate job.json` |
| `--out` / `--job-id` | render, submit | Single-cell `N=1` only. Default job dir is under `filelists_dir`. `job-id` is Pushgateway `replica`, not a Grafana dimension |
| `--site-map` | resolve, render, submit | If the sidecar has no `rse` column. Else YAML `site_map:` or `filelists_dir/site_map.csv` |
| `--pool` / `--schedd` | submit, jobs, rm | Override YAML `condor_pool` / `condor_schedd`. Pool is the collector (`-pool`), not a schedd |
| `--arch` | payload | Default `linux-amd64` (el9) |

```sh
uv run tckestrel plan --config examples/controller.yaml
uv run tckestrel payload --config examples/controller.yaml
uv run tckestrel submit --config examples/controller.yaml --dry-run
uv run tckestrel submit --config examples/controller.yaml
uv run tckestrel jobs --config examples/controller.yaml
uv run tckestrel rm --config examples/controller.yaml
```

`resolve` needs a CMS VOMS proxy (`source /cvmfs/cms.cern.ch/rucio/setup.sh`). Packaged client endpoints: `cms-rucio.cern.ch`, `x509_proxy`. `ca_cert` from `X509_CERT_DIR`, then CVMFS grid certs, then `/etc/grid-security/certificates`. Override with `RUCIO_CONFIG`.

`chunk_bytes` is one XRootD `Read()` (`pattern.read_size`, default 8 MB, max 8 MB). `max_bytes` is bytes from one file. `target_rate_sum_gbps` scales the Spark matrix. A submit takes LFNs for `cell_rate × job_duration_s`, not the whole sidecar.

## payload

Fetch the [linux-amd64 release](https://github.com/dynamic-entropy/xrdhover/releases) if that file is missing. That artifact name means **el9 amd64** (glibc 2.34, OpenSSL 3). An el10-built tarball will fail on `rhel9` glideins (`GLIBC_` / `GLIBCXX_`). Condor transfers the file as input; `run_xrdhover.sh` is the executable. The WN glidein does not provide `libXrdCl.so.6`. The wrapper cmsenv’s `cmssw` (default `CMSSW_20_1_0_pre2`, XRootD 6.0.2 on el9) so that library is on `LD_LIBRARY_PATH`. 15.x–20.0 CMSSW still ship XRootD 5 and will not load the binary.

| YAML key | Default |
|---|---|
| `xrdhover_version` | `latest` |
| `xrdhover_dir` | `$HOME/vendor/xrdhover` |
| `xrdhover` | (unset; pin a file) |
| `cmssw` | `CMSSW_20_1_0_pre2` (XRootD 6.0.2; must stay 6.x) |
| `required_os` | `rhel9` (must match `cmssw` arch) |

## submit file

| Submit attribute | Value |
|---|---|
| `executable` | `run_xrdhover.sh` (CMSSW cmsenv, then `xrdhover`) |
| `transfer_executable` | `true` |
| `arguments` | `-C CMSSW_20_1_0_pre2 -- run job.json` (`cmssw` in the YAML) |
| `transfer_input_files` | `job.json, files.txt`, plus the xrdhover binary |
| `should_transfer_output` | `YES` (`results/` and stdout/stderr back to the job dir) |
| `when_to_transfer_output` | `ON_EXIT_OR_EVICT` |
| `output` / `error` | `logs/$(Cluster).$(Process).{out,err}` under the job dir |
| `log` | `{filelists_dir}/.tckestrel/condor.log` (campaign event log) |
| `job_machine_attrs` | `GLIDEIN_CMSSite` (copied onto the job as `MachineAttrGLIDEIN_CMSSite0`) |
| `x509userproxy` | `$ENV(X509_USER_PROXY)` when that file exists |
| `request_cpus` | `request_cpus` in the YAML (default `1`) |
| `request_memory` | `request_memory_mb` (default `2048`) |
| `request_disk` | `request_disk_mb` (default `2048`) |
| `keep_claim_idle` | `keep_claim_idle` in the YAML (default `600` seconds) |
| `+DESIRED_Sites` | dest CMS site (where the job runs) |
| `+REQUIRED_OS` | `required_os` in the YAML (default `rhel9`) |
| `+DesiredOS` | `REQUIRED_OS` (CMS Connect, same as test.jdl) |

## Tests

```sh
uv run pytest
```
