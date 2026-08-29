# tckestrel

Fleet controller for [xrdhover](https://github.com/dynamic-entropy/xrdhover) WAN-hold jobs on HTCondor.

Managed with [uv](https://docs.astral.sh/uv/).

## Install

```sh
uv sync --group dev
```

## Plan a campaign

Given a controller YAML and rate matrix (and optionally a Spark `filelists_dir`):

```sh
uv run tckestrel plan --config tests/fixtures/controller.yaml

```

`--config` is a path; there is no `controller.yaml` at the repo root. Prints one row per matrix cell: `source`, `dest`, `rate_gbps`, `N`, `job_rate_gbps`, `rse`, `n_files`, `shortfall`. Does not submit jobs or call Rucio.

Paths in the YAML (`matrix`, `filelists_dir`) are resolved relative to the config file, then the current working directory.

## Tests

```sh
uv run pytest
```
