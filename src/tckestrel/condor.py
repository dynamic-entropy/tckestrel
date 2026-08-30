"""HTCondor submit description, query, and remove."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from tckestrel.config import DEFAULT_CMSSW, DEFAULT_KEEP_CLAIM_IDLE_S

_CLUSTER_RE = re.compile(r"submitted to cluster (\d+)", re.I)

LOG_DIR = "logs"
WRAPPER_NAME = "run_xrdhover.sh"
PAYLOAD_NAME = "xrdhover"

JOB_STATUS = {
    1: "Idle",
    2: "Running",
    3: "Removed",
    4: "Completed",
    5: "Held",
    6: "Transferring",
}


class CondorError(RuntimeError):
    """Schedd submit, query, or remove failed."""


@dataclass(frozen=True)
class SubmitSpec:
    executable: Path
    job_dir: Path
    dest: str
    campaign_id: str
    source: str
    run_id: str
    job_id: str
    proxy: Path | None = None
    required_os: str = "rhel9"
    request_cpus: int = 1
    request_memory_mb: int = 2048
    request_disk_mb: int = 2048
    event_log: Path | None = None
    payload: Path | None = None
    cmssw: str = DEFAULT_CMSSW
    keep_claim_idle_s: int = DEFAULT_KEEP_CLAIM_IDLE_S


@dataclass(frozen=True)
class SubmitResult:
    cluster: int
    proc: int = 0

    @property
    def cluster_proc(self) -> str:
        return f"{self.cluster}.{self.proc}"


@dataclass(frozen=True)
class CondorJob:
    cluster: int
    proc: int
    status: str
    dest: str
    source: str
    campaign_id: str
    run_id: str
    job_id: str


class CondorBackend(Protocol):
    def submit(self, spec: SubmitSpec) -> SubmitResult: ...

    def query(
        self,
        campaign_id: str,
        source: str | None = None,
        dest: str | None = None,
    ) -> list[CondorJob]: ...

    def remove(
        self,
        campaign_id: str,
        source: str | None = None,
        dest: str | None = None,
    ) -> int: ...


def ad_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def campaign_constraint(
    campaign_id: str,
    source: str | None = None,
    dest: str | None = None,
) -> str:
    parts = [f"TckestrelCampaign == {ad_string(campaign_id)}"]
    if source:
        parts.append(f"TckestrelSource == {ad_string(source)}")
    if dest:
        parts.append(f"TckestrelDest == {ad_string(dest)}")
    return " && ".join(parts)


def submit_items(spec: SubmitSpec) -> dict[str, str]:
    items = {
        "universe": "vanilla",
        "executable": str(spec.executable),
        "transfer_executable": "true",
        "arguments": f"-C {spec.cmssw} -- run job.json",
        "transfer_input_files": (
            f"job.json, files.txt, {spec.payload}"
            if spec.payload is not None
            else "job.json, files.txt"
        ),
        "should_transfer_files": "YES",
        "should_transfer_output": "YES",
        "when_to_transfer_output": "ON_EXIT_OR_EVICT",
        "initialdir": str(spec.job_dir),
        "output": f"{LOG_DIR}/$(Cluster).$(Process).out",
        "error": f"{LOG_DIR}/$(Cluster).$(Process).err",
        "log": str(spec.event_log)
        if spec.event_log is not None
        else f"{LOG_DIR}/$(Cluster).$(Process).log",
        "job_machine_attrs": "GLIDEIN_CMSSite",
        "use_x509userproxy": "true",
        "x509userproxy": "$ENV(X509_USER_PROXY)",
        "request_cpus": str(spec.request_cpus),
        "request_memory": f"{spec.request_memory_mb}MB",
        "request_disk": f"{spec.request_disk_mb}MB",
        "keep_claim_idle": str(spec.keep_claim_idle_s),
        "+REQUIRED_OS": ad_string(spec.required_os),
        "+DesiredOS": "REQUIRED_OS",
        "+TckestrelCampaign": ad_string(spec.campaign_id),
        "+TckestrelSource": ad_string(spec.source),
        "+TckestrelDest": ad_string(spec.dest),
        "+TckestrelRunId": ad_string(spec.run_id),
        "+TckestrelJobId": ad_string(spec.job_id),
        "+DESIRED_Sites": ad_string(spec.dest),
    }
    return items


def submit_text(spec: SubmitSpec) -> str:
    lines = [f"{key:24s}= {value}" for key, value in submit_items(spec).items()]
    lines.append("queue")
    return "\n".join(lines) + "\n"


def proxy_path() -> Path | None:
    raw = os.environ.get("X509_USER_PROXY")
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_file() else None


def _import_htcondor():
    try:
        import htcondor2 as htcondor  # type: ignore[import-not-found]
    except ImportError:
        try:
            import htcondor  # type: ignore[import-not-found]
        except ImportError as exc:
            raise CondorError(
                "htcondor2 (or htcondor) is not importable; use the submit-host install"
            ) from exc
    return htcondor


def condor_argv(
    tool: str,
    *args: str,
    pool: str | None = None,
    schedd: str | None = None,
) -> list[str]:
    cmd = [tool]
    if pool:
        cmd.extend(["-pool", pool])
    if schedd:
        if tool == "condor_submit":
            cmd.extend(["-remote", schedd])
        else:
            cmd.extend(["-name", schedd])
    cmd.extend(args)
    return cmd


def _run_condor(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(cmd, check=False, capture_output=True, text=True)
    except OSError as exc:
        raise CondorError(f"{cmd[0]} failed: {exc}") from exc


def _job_from_ad(ad: object) -> CondorJob:
    status = int(ad.get("JobStatus", 0))
    return CondorJob(
        cluster=int(ad.get("ClusterId", 0)),
        proc=int(ad.get("ProcId", 0)),
        status=JOB_STATUS.get(status, str(status)),
        dest=str(ad.get("DESIRED_Sites") or ad.get("TckestrelDest") or ""),
        source=str(ad.get("TckestrelSource") or ""),
        campaign_id=str(ad.get("TckestrelCampaign") or ""),
        run_id=str(ad.get("TckestrelRunId") or ""),
        job_id=str(ad.get("TckestrelJobId") or ""),
    )


class LiveCondor:
    def __init__(self, pool: str | None = None, schedd: str | None = None) -> None:
        self.pool = pool or None
        self.schedd = schedd or None

    def submit(self, spec: SubmitSpec) -> SubmitResult:
        # Site condor_submit: the PyPI htcondor2 Submit() API injects a
        # CondorVersion >= 25.12 requirement that CMS glideins do not satisfy.
        # condor_pool is -pool only; -remote/-name need an explicit schedd.
        sub = spec.job_dir / "job.sub"
        if not sub.is_file():
            sub.write_text(submit_text(spec), encoding="utf-8")
        proc = _run_condor(
            condor_argv("condor_submit", str(sub), pool=self.pool, schedd=self.schedd)
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            raise CondorError(f"condor_submit failed ({proc.returncode}): {err}")
        match = _CLUSTER_RE.search(proc.stdout) or _CLUSTER_RE.search(proc.stderr)
        if match is None:
            raise CondorError("condor_submit returned no cluster id")
        cluster = int(match.group(1))
        return SubmitResult(cluster=cluster, proc=0)

    def query(
        self,
        campaign_id: str,
        source: str | None = None,
        dest: str | None = None,
    ) -> list[CondorJob]:
        if self.pool or self.schedd:
            return self._query_cli(campaign_id, source, dest)
        htcondor = _import_htcondor()
        constraint = campaign_constraint(campaign_id, source, dest)
        projection = [
            "ClusterId",
            "ProcId",
            "JobStatus",
            "DESIRED_Sites",
            "TckestrelCampaign",
            "TckestrelSource",
            "TckestrelDest",
            "TckestrelRunId",
            "TckestrelJobId",
        ]
        try:
            ads = htcondor.Schedd().query(constraint=constraint, projection=projection)
        except Exception as exc:
            raise CondorError(str(exc)) from exc
        return [_job_from_ad(ad) for ad in ads]

    def _query_cli(
        self,
        campaign_id: str,
        source: str | None,
        dest: str | None,
    ) -> list[CondorJob]:
        constraint = campaign_constraint(campaign_id, source, dest)
        proc = _run_condor(
            condor_argv(
                "condor_q",
                "-const",
                constraint,
                "-af",
                "ClusterId",
                "ProcId",
                "JobStatus",
                "DESIRED_Sites",
                "TckestrelSource",
                "TckestrelCampaign",
                "TckestrelDest",
                "TckestrelRunId",
                "TckestrelJobId",
                pool=self.pool,
                schedd=self.schedd,
            )
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            raise CondorError(f"condor_q failed ({proc.returncode}): {err}")
        rows: list[CondorJob] = []
        for line in proc.stdout.splitlines():
            fields = line.split(None, 8)
            if len(fields) < 9:
                continue
            status = int(fields[2]) if fields[2].isdigit() else 0
            rows.append(
                CondorJob(
                    cluster=int(fields[0]),
                    proc=int(fields[1]) if fields[1].isdigit() else 0,
                    status=JOB_STATUS.get(status, fields[2]),
                    dest=fields[3],
                    source=fields[4],
                    campaign_id=fields[5],
                    run_id=fields[7],
                    job_id=fields[8],
                )
            )
        return rows

    def remove(
        self,
        campaign_id: str,
        source: str | None = None,
        dest: str | None = None,
    ) -> int:
        constraint = campaign_constraint(campaign_id, source, dest)
        if self.pool or self.schedd:
            proc = _run_condor(
                condor_argv(
                    "condor_rm",
                    "-constraint",
                    constraint,
                    pool=self.pool,
                    schedd=self.schedd,
                )
            )
            if proc.returncode != 0:
                err = (proc.stderr or proc.stdout or "").strip()
                raise CondorError(f"condor_rm failed ({proc.returncode}): {err}")
            return sum(1 for line in proc.stdout.splitlines() if "marked for removal" in line)
        htcondor = _import_htcondor()
        try:
            result = htcondor.Schedd().act(htcondor.JobAction.Remove, constraint)
        except Exception as exc:
            raise CondorError(str(exc)) from exc
        total = getattr(result, "total", None)
        if callable(total):
            return int(total())
        if isinstance(result, dict):
            return int(result.get("TotalSuccess", 0) or result.get("total", 0) or 0)
        return 0


class RecordingCondor:
    def __init__(self) -> None:
        self.submitted: list[SubmitSpec] = []
        self.jobs: list[CondorJob] = []
        self.removed: list[str] = []
        self.next_cluster = 100

    def submit(self, spec: SubmitSpec) -> SubmitResult:
        self.submitted.append(spec)
        cluster = self.next_cluster
        self.next_cluster += 1
        self.jobs.append(
            CondorJob(
                cluster=cluster,
                proc=0,
                status="Idle",
                dest=spec.dest,
                source=spec.source,
                campaign_id=spec.campaign_id,
                run_id=spec.run_id,
                job_id=spec.job_id,
            )
        )
        return SubmitResult(cluster=cluster, proc=0)

    def query(
        self,
        campaign_id: str,
        source: str | None = None,
        dest: str | None = None,
    ) -> list[CondorJob]:
        rows = [job for job in self.jobs if job.campaign_id == campaign_id]
        if source:
            rows = [job for job in rows if job.source == source]
        if dest:
            rows = [job for job in rows if job.dest == dest]
        return rows

    def remove(
        self,
        campaign_id: str,
        source: str | None = None,
        dest: str | None = None,
    ) -> int:
        self.removed.append(campaign_constraint(campaign_id, source, dest))
        before = len(self.jobs)
        remaining: list[CondorJob] = []
        for job in self.jobs:
            match = job.campaign_id == campaign_id
            if source:
                match = match and job.source == source
            if dest:
                match = match and job.dest == dest
            if not match:
                remaining.append(job)
        self.jobs = remaining
        return before - len(self.jobs)
