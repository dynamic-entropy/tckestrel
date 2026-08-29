# tckestrel

Fleet controller for [xrdhover](https://github.com/dynamic-entropy/xrdhover) WAN-hold jobs on HTCondor.

Managed with [uv](https://docs.astral.sh/uv/).

## Install

```sh
uv sync --group dev
```

Runtime needs only PyYAML. `rucio-clients` is in the **dev** group for this laptop. On the schedd, `uv sync` (no group) and use the machine’s Rucio (`source /cvmfs/cms.cern.ch/rucio/setup.sh` so `import rucio` works). Do not pin the schedd client version.

## Plan a campaign

Given a controller YAML and rate matrix (and optionally a Spark `filelists_dir`):

```sh
uv run tckestrel plan --config tests/fixtures/controller.yaml

```

`--config` is a path; there is no `controller.yaml` at the repo root. Prints one row per matrix cell: `source`, `dest`, `rate_gbps`, `N`, `job_rate_gbps`, `rse`, `n_files`, `shortfall`. Does not submit jobs or call Rucio.

## Resolve PFNs

Stamp a cell's LFNs with pinned `root://` PFNs (Rucio `lfns2pfns`, then a per-RSE prefix cache). Rejects AAA redirectors. Does not submit jobs.

Uses the packaged CMS client endpoints (`cms-rucio.cern.ch`, `x509_proxy`). `ca_cert` is filled in at runtime: `X509_CERT_DIR`, then CVMFS (`/cvmfs/cms.cern.ch/grid/etc/grid-security/certificates`), then `/etc/grid-security/certificates`. Override the whole file with `RUCIO_CONFIG`. Needs a CMS VOMS proxy. On a CVMFS host, `source /cvmfs/cms.cern.ch/rucio/setup.sh` and `rucio whoami` is a useful check. Use a real campaign, not `tests/fixtures` (those LFNs are fake).

```sh
uv run tckestrel resolve --config examples/controller.yaml --cell T2_CH_CERN,T1_US_FNAL --limit 3
```

Old Spark lists without an `rse` column use `--site-map` (or `site_map:` in the YAML, or `filelists_dir/site_map.csv`).

Paths in the YAML (`matrix`, `filelists_dir`, `site_map`) are resolved relative to the config file, then the current working directory.

## Tests

```sh
uv run pytest
```
