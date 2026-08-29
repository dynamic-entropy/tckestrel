"""Per-RSE prefix cache (memory + JSON on disk)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from tckestrel.pfn import derive_prefix, parse_root_pfn


@dataclass(frozen=True)
class RseTemplate:
    rse: str
    host: str
    port: int
    prefix: str
    example_pfn: str


class PrefixCache:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self._mem: dict[str, RseTemplate] = {}
        if path is not None and path.is_file():
            raw = json.loads(path.read_text(encoding="utf-8"))
            for rse, row in raw.items():
                self._mem[rse] = RseTemplate(rse=rse, **row)

    def get(self, rse: str) -> RseTemplate | None:
        return self._mem.get(rse)

    def learn(self, rse: str, lfn: str, pfn: str) -> RseTemplate:
        parsed = parse_root_pfn(pfn)
        template = RseTemplate(
            rse=rse,
            host=parsed.host,
            port=parsed.port,
            prefix=derive_prefix(parsed.path, lfn),
            example_pfn=pfn,
        )
        self._mem[rse] = template
        self._flush()
        return template

    def _flush(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            rse: {k: v for k, v in asdict(row).items() if k != "rse"}
            for rse, row in self._mem.items()
        }
        self.path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
