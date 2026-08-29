"""HTCondor submit description, query, and remove."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

_CLUSTER_RE = re.compile(r"submitted to cluster (\d+)", re.I)

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
    desired_sites: str | None = None


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
        "arguments": "run job.json",
        "transfer_input_files": "job.json, files.txt",
        "should_transfer_files": "YES",
        "initialdir": str(spec.job_dir),
        "output": "job.out",
        "error": "job.err",
        "log": "job.log",
        "use_x509userproxy": "true",
        "+REQUIRED_OS": ad_string(spec.required_os),
        "+TckestrelCampaign": ad_string(spec.campaign_id),
        "+TckestrelSource": ad_string(spec.source),
        "+TckestrelDest": ad_string(spec.dest),
        "+TckestrelRunId": ad_string(spec.run_id),
        "+TckestrelJobId": ad_string(spec.job_id),
    }
    site = spec.dest if spec.desired_sites is None else spec.desired_sites
    if site:
        items["+DESIRED_Sites"] = ad_string(site)
    if spec.proxy is not None:
        items["x509userproxy"] = str(spec.proxy)
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
    def submit(self, spec: SubmitSpec) -> SubmitResult:
        # Site condor_submit: the PyPI htcondor2 Submit() API injects a
        # CondorVersion >= 25.12 requirement that CMS glideins do not satisfy.
        sub = spec.job_dir / "job.sub"
        if not sub.is_file():
            sub.write_text(submit_text(spec), encoding="utf-8")
        try:
            proc = subprocess.run(
                ["condor_submit", str(sub)],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError as exc:
            raise CondorError(f"condor_submit failed: {exc}") from exc
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            raise CondorError(f"condor_submit failed ({proc.returncode}): {err}")
        match = _CLUSTER_RE.search(proc.stdout) or _CLUSTER_RE.search(proc.stderr)
        if match is None:
            raise CondorError("condor_submit returned no cluster id")
        return SubmitResult(cluster=int(match.group(1)), proc=0)

    def query(
        self,
        campaign_id: str,
        source: str | None = None,
        dest: str | None = None,
    ) -> list[CondorJob]:
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

    def remove(
        self,
        campaign_id: str,
        source: str | None = None,
        dest: str | None = None,
    ) -> int:
        htcondor = _import_htcondor()
        constraint = campaign_constraint(campaign_id, source, dest)
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
