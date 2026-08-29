# tckestrel

Fleet controller for [xrdhover](https://github.com/dynamic-entropy/xrdhover) WAN-hold jobs on HTCondor.

Managed with [uv](https://docs.astral.sh/uv/).

## Install

```sh
uv sync --group dev
```

Runtime depends on PyYAML. `rucio-clients` is in the **dev** group. On a submit host, `uv sync` (no group) and use the Rucio already on that machine (`source /cvmfs/cms.cern.ch/rucio/setup.sh`).

## Plan a campaign

```sh
uv run tckestrel plan --config tests/fixtures/controller.yaml
```

`--config` is a path. Prints one row per matrix cell: `source`, `dest`, `rate_gbps`, `N`, `job_rate_gbps`, `rse`, `n_files`, `shortfall`. Does not submit jobs or call Rucio.

## Resolve PFNs

Stamp a cell's LFNs with pinned `root://` PFNs (Rucio `lfns2pfns`, then a per-RSE prefix cache). Rejects AAA redirectors. Does not submit jobs.

Uses the packaged CMS client endpoints (`cms-rucio.cern.ch`, `x509_proxy`). `ca_cert` is `X509_CERT_DIR`, then `/cvmfs/cms.cern.ch/grid/etc/grid-security/certificates`, then `/etc/grid-security/certificates`. Override the file with `RUCIO_CONFIG`. Requires a CMS VOMS proxy.

```sh
uv run tckestrel resolve --config examples/controller.yaml --cell T2_CH_CERN,T1_US_FNAL --limit 3
```

Lists without an `rse` column use `--site-map` (or `site_map:` in the YAML, or `filelists_dir/site_map.csv`).

## xrdhover binary

`tckestrel payload` fetches the [linux-amd64 release](https://github.com/dynamic-entropy/xrdhover/releases) into `$HOME/vendor/xrdhover/<version>/<arch>/xrdhover` if that file is missing. Condor transfers that file (`transfer_executable`). Worker nodes need `xrootd-client`. Submit will call the same ensure step and later choose `<arch>` from the dest site.

```sh
uv run tckestrel payload --config examples/controller.yaml
```

Optional YAML: `xrdhover_version` (default `latest`), `xrdhover_dir` (default `$HOME/vendor/xrdhover`), or `xrdhover` to pin a file.

Paths in the YAML (`matrix`, `filelists_dir`, `site_map`, `xrdhover`, `xrdhover_dir`) are resolved relative to the config file, then the current working directory. `$HOME` and `~` are expanded.

## Tests

```sh
uv run pytest
```
