# tckestrel

Fleet controller for [xrdhover](https://github.com/dynamic-entropy/xrdhover) WAN-hold jobs on HTCondor.

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

Fetch the [linux-amd64 release](https://github.com/dynamic-entropy/xrdhover/releases) into `$HOME/vendor/xrdhover/<version>/<arch>/xrdhover` if that file is missing. Condor transfers the file (`transfer_executable`). Worker nodes require `xrootd-client`.

```sh
uv run tckestrel payload --config examples/controller.yaml
```

| YAML key | Default |
|---|---|
| `xrdhover_version` | `latest` |
| `xrdhover_dir` | `$HOME/vendor/xrdhover` |
| `xrdhover` | (unset; pin a file) |

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
| `executable` | path from `tckestrel payload` |
| `transfer_executable` | `true` |
| `arguments` | `run job.json` |
| `transfer_input_files` | `job.json, files.txt` |
| `+DESIRED_Sites` | dest CMS site |
| `x509userproxy` | `X509_USER_PROXY` when that file exists |

`jobs` and `rm` select on `TckestrelCampaign`, optionally `TckestrelSource` and `TckestrelDest`.

## Tests

```sh
uv run pytest
```
