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

## plan

```sh
uv run tckestrel plan --config tests/fixtures/controller.yaml
```

One row per matrix cell: `source`, `dest`, `rate_gbps`, `N`, `job_rate_gbps`, `rse`, `n_files`, `shortfall`.

## resolve

Stamp a cell's LFNs with pinned `root://` PFNs (`RSEClient.lfns2pfns`, then a per-RSE prefix cache). AAA redirectors are rejected.

Uses the packaged CMS client endpoints (`cms-rucio.cern.ch`, `x509_proxy`). `ca_cert` is taken from `X509_CERT_DIR`, then `/cvmfs/cms.cern.ch/grid/etc/grid-security/certificates`, then `/etc/grid-security/certificates`. Override the client file with `RUCIO_CONFIG`. Requires a CMS VOMS proxy.

```sh
uv run tckestrel resolve --config examples/controller.yaml --cell T2_CH_CERN,T1_US_FNAL --limit 3
```

Lists without an `rse` column use `--site-map`, `site_map:` in the YAML, or `filelists_dir/site_map.csv`.

## render

Write `job.json` and `files.txt` for one cell.

```sh
uv run tckestrel render --config examples/controller.yaml --cell T2_CH_CERN,T1_US_FNAL --limit 3
```

`--out` sets the output directory. `--job-id` sets `sinks.job_id` (default: a new UUID). `--validate` runs `xrdhover validate` on the written JSON.

## payload

Fetch the [linux-amd64 release](https://github.com/dynamic-entropy/xrdhover/releases) into `$HOME/vendor/xrdhover/<version>/<arch>/xrdhover` if that file is missing. That artifact name means **el9 amd64** (glibc 2.34, OpenSSL 3). An el10-built tarball will fail on `rhel9` glideins (`GLIBC_` / `GLIBCXX_`). Condor transfers the file as input; `run_xrdhover.sh` is the executable. The WN glidein does not provide `libXrdCl.so.6`. The wrapper cmsenv’s `cmssw` (default `CMSSW_20_1_0_pre2`, XRootD 6.0.2 on el9) so that library is on `LD_LIBRARY_PATH`. 15.x–20.0 CMSSW still ship XRootD 5 and will not load the binary.

```sh
uv run tckestrel payload --config examples/controller.yaml
```

| YAML key | Default |
|---|---|
| `xrdhover_version` | `latest` |
| `xrdhover_dir` | `$HOME/vendor/xrdhover` |
| `xrdhover` | (unset; pin a file) |
| `cmssw` | `CMSSW_20_1_0_pre2` (XRootD 6.0.2; must stay 6.x) |
| `required_os` | `rhel9` (must match `cmssw` arch) |

## submit

Write `job.sub` next to `job.json` and `files.txt`. `--submit` queues the job on the schedd.

```sh
uv run tckestrel submit --config examples/controller.yaml --cell T2_CH_CERN,T1_US_FNAL --limit 3
uv run tckestrel submit --config examples/controller.yaml --cell T2_CH_CERN,T1_US_FNAL --limit 3 --submit
uv run tckestrel jobs --config examples/controller.yaml
uv run tckestrel rm --config examples/controller.yaml --cell T2_CH_CERN,T1_US_FNAL
```

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
| `x509userproxy` | `$ENV(X509_USER_PROXY)` |
| `request_cpus` | `request_cpus` in the YAML (default `1`) |
| `request_memory` | `request_memory_mb` (default `2048`) |
| `request_disk` | `request_disk_mb` (default `2048`) |
| `keep_claim_idle` | `keep_claim_idle` in the YAML (default `600` seconds) |
| `+DESIRED_Sites` | dest CMS site (where the job runs) |
| `+REQUIRED_OS` | `required_os` in the YAML (default `rhel9`) |
| `+DesiredOS` | `REQUIRED_OS` (CMS Connect, same as test.jdl) |
| `x509userproxy` | `X509_USER_PROXY` when that file exists |

`jobs` and `rm` select on `TckestrelCampaign`, optionally `TckestrelSource` and `TckestrelDest`.

`condor_pool` / `--pool` is `condor_submit -pool …` (and the same flag on `jobs` / `rm`). That names a collector, not a schedd. `condor_schedd` / `--schedd` is optional and adds `-remote` / `-name`.

## Tests

```sh
uv run pytest
```
