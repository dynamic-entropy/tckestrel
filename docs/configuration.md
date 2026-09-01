# Controller YAML

tckestrel reads one nested YAML file (`--config`). Keys live under the CLI command that uses them. Flat (unsectioned) keys are rejected.

Paths (`matrix`, `filelists_dir`, `site_map`, `payload.binary`, `payload.cache_dir`) are resolved relative to this file, then the current working directory. `$HOME` and `~` are expanded.

`plan` and `submit` are required sections. `payload` and `loop` are optional (defaults apply). The live file is edited on the CMS Connect schedd (`cmscon`); a local `examples/controller.yaml` is not used on submit.

```yaml
campaign_id: premix-2026-08-29
matrix: output/bidirectional.csv
filelists_dir: output/2026-08-29/tckestrel_premix

plan:
  max_job_rate_gbps: 0.2
  min_jobs_per_cell: 1
  read_size_bytes: 8000000
  max_bytes_per_file: 32000000
  job_duration_s: 1800
  target_rate_sum_gbps: 0.4

payload:
  xrdhover_version: "0.3.0"
  required_os: rhel9

submit:
  pushgateway_url: https://xrdprom.cern.ch:2094
  snapshot_interval_s: 15
  condor_pool: vocms4100.cern.ch
  request_cpus: 1
  request_memory_mb: 1024
  request_disk_mb: 1024
  proxy_min_ttl_s: 25200

loop:
  max_idle_jobs_per_cell: 4
  max_idle_jobs_per_dest: 20
  max_jobs_per_dest: 50
  max_jobs_global: 200
  submits_per_minute: 10
  min_job_lifetime_s: 120
  recycle_lfn_after_s: 7200
  rate_deadband_frac: 0.05
  ramp_jobs_per_tick: 1
```

## Campaign

| Key | Required | Default | What it does |
|---|---|---|---|
| `campaign_id` | yes | | Name stamped on every Condor job (`TckestrelCampaign`) and used by `jobs` / `rm`. |
| `matrix` | yes | | Path to the source×dest rate CSV (Gbps). Rows are source CMS sites; columns are dest CMS sites (`+DESIRED_Sites`). `0` / blank = no link. |
| `filelists_dir` | no | | Spark campaign directory (`links.csv` + `filelists/`). Required before resolve / render / submit. |
| `site_map` | no | `filelists_dir/site_map.csv` if that file exists | CMS site → Rucio RSE when the sidecar has no `rse` column. |

## `plan`

Used by `tckestrel plan` (and by submit, which walks the plan). For each matrix cell rate `R`:

```text
N = max(min_jobs_per_cell, ceil(R / max_job_rate_gbps))
job_rate_gbps = R / N
```

`N` is the number of Condor jobs for that cell. It is **not** xrdhover `max_inflight` (concurrent Reads inside one process).

| Key | Required | Default | What it does |
|---|---|---|---|
| `max_job_rate_gbps` | yes | | Cap on one job’s xrdhover `--rate`. A crash costs this much throughput until replenish. Must be > 0. |
| `min_jobs_per_cell` | yes | | Floor on `N`. Integer ≥ 1. |
| `read_size_bytes` | no | `8000000` (8 MB) | One XRootD `Read()` (`pattern.read_size`). Max 8 MB. Not the LFN-pool slice and not bytes-per-file. |
| `max_bytes_per_file` | no | `32000000` (32 MB) | Bytes read from one file then close (`pattern.max_bytes`). Do not set this to a PREMIX file size. |
| `job_duration_s` | no | `7200` | Job wall clock. A submit takes sidecar LFNs until `cell_rate × job_duration_s` bytes, not the whole Spark list. Live hold: `1800`. |
| `target_rate_sum_gbps` | no | unset (use matrix as-is) | Scale every matrix cell uniformly so rates sum to this. Spark 200 Gbps campaign → `10` for a 10 Gbps hold. |

Changing `max_job_rate_gbps` or `min_jobs_per_cell` does not require a Spark rerun. Changing which sites or rates are in the matrix does.

## `payload`

Used by `tckestrel payload` and by submit (which fetches if needed). The WN glidein does not provide `libXrdCl.so.6`; `run_xrdhover.sh` cmsenv’s `cmssw` so that library is on `LD_LIBRARY_PATH`. Fetched `linux-amd64` is an AlmaLinux 9 binary — do not cache an el10 tarball under that name.

| Key | Required | Default | What it does |
|---|---|---|---|
| `xrdhover_version` | no | `latest` | GitHub release tag (`latest` or `0.3.0`; a leading `v` is stripped). |
| `cache_dir` | no | `$HOME/vendor/xrdhover` | Cache root: `<cache_dir>/<version>/<arch>/xrdhover`. |
| `binary` | no | unset | Pin a file; skips fetch for `linux-amd64`. Other arches still use `cache_dir`. Pin an el9 binary. |
| `cmssw` | no | `CMSSW_20_1_0_pre2` | CVMFS release for cmsenv. Must ship XRootD 6 (`libXrdCl.so.6`). 15.x–20.0 still ship XRootD 5. |
| `required_os` | no | `rhel9` | Condor `+REQUIRED_OS`. Must match `cmssw` (`el9_*` → `rhel9`) and the payload ABI. |

## `submit`

Used by `tckestrel submit` (and `jobs` / `rm` for the pool). `condor_pool` is a collector (`condor_submit -pool`). It is not a schedd. Do not set `condor_schedd: vocms4100.cern.ch`.

| Key | Required | Default | What it does |
|---|---|---|---|
| `pushgateway_url` | yes | | Pushgateway base URL written into `job.json`. Campaign: `https://xrdprom.cern.ch:2094`. |
| `snapshot_interval_s` | no | `15` | How often xrdhover snapshots / pushes (`sinks.snapshot_interval`). |
| `condor_pool` | no | unset (local schedd) | Collector host for `-pool`. |
| `condor_schedd` | no | unset | Only if you have a real schedd name; then `-remote` / `-name`. |
| `request_cpus` | no | `1` | Condor `request_cpus`. |
| `request_memory_mb` | no | `2048` | Condor `request_memory`. |
| `request_disk_mb` | no | `2048` | Condor `request_disk`. |
| `keep_claim_idle_s` | no | `600` | Seconds the schedd holds the slot after exit for a matching follow-on. `0` disables. CMS pilots may still die after one job. |
| `proxy_min_ttl_s` | no | unset | Loaded; not checked yet. Intended remaining proxy TTL at Execute (≥ duration + 300s). |

## `loop`

Not a CLI command yet (dev_plan step 7). Values are **loaded and validated** and do not actuate. Idle jobs count as inflight and produce zero rate — that is why the idle caps exist.

| Key | Required | Default | What it does |
|---|---|---|---|
| `max_idle_jobs_per_cell` | no | `4` | Max Idle jobs on one matrix cell. Stops submitting because Mbps is low while dest is still matching. |
| `max_idle_jobs_per_dest` | no | `20` | Max Idle at one dest, summed across cells that land there. |
| `max_jobs_per_dest` | no | `50` | Max Idle+Running at one dest. |
| `max_jobs_global` | no | `200` | Max Idle+Running in the campaign. |
| `submits_per_minute` | no | `10` | Submit drip. Matchmaking delay overshoots if the whole deficit is queued in one tick. |
| `min_job_lifetime_s` | no | `120` | Do not kill a job younger than this (token-bucket burst + scrape lag look like failure). |
| `recycle_lfn_after_s` | no | `7200` | Reuse LFNs only after ~2 h cache TTL, and only on sidecar `shortfall`. |
| `rate_deadband_frac` | no | `0.05` | Skip actuation if achieved rate is within this fraction of target. |
| `ramp_jobs_per_tick` | no | `1` | Max new jobs added on one control tick. |
