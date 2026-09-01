from pathlib import Path

import pytest

from tckestrel.matrix import MatrixError, load_cells
from tckestrel.plan import derive_job_rate, derive_n


def test_example_matrix_has_six_cells(fixtures_dir: Path) -> None:
    cells = load_cells(fixtures_dir / "matrix.csv")
    assert len(cells) == 6
    pairs = {(c.source, c.dest) for c in cells}
    assert pairs == {
        ("T2_CH_CERN", "T1_US_FNAL"),
        ("T2_CH_CERN", "T1_DE_KIT"),
        ("T2_CH_CERN", "T2_US_UCSD"),
        ("T1_US_FNAL", "T2_CH_CERN"),
        ("T1_US_FNAL", "T1_DE_KIT"),
        ("T1_US_FNAL", "T2_US_UCSD"),
    }
    assert all(c.rate_gbps == 0.017 for c in cells)
    assert all(c.source != c.dest for c in cells)


def test_rejects_rse_dest_headers(fixtures_dir: Path) -> None:
    with pytest.raises(MatrixError, match="CMS sites"):
        load_cells(fixtures_dir / "rse_dest_matrix.csv")


@pytest.mark.parametrize(
    ("rate", "max_rate", "min_jobs_per_cell", "n", "job_rate"),
    [
        (0.017, 0.1, 1, 1, 0.017),
        (1.0, 0.1, 1, 10, 0.1),
        (0.017, 0.1, 3, 3, 0.017 / 3),
    ],
)
def test_n_and_job_rate(
    rate: float,
    max_rate: float,
    min_jobs_per_cell: int,
    n: int,
    job_rate: float,
) -> None:
    got_n = derive_n(rate, max_rate, min_jobs_per_cell)
    got_rate = derive_job_rate(rate, got_n)
    assert got_n == n
    assert got_n >= min_jobs_per_cell
    assert got_rate <= max_rate + 1e-12
    assert got_rate == pytest.approx(job_rate)
    assert got_n * got_rate == pytest.approx(rate)
