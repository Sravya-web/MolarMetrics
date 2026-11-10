"""Synthetic dataset: reproducibility, overwrite protection and data rules."""

import hashlib
import json

import pytest

from molarmetrics.data.catalog import DENTISTS
from molarmetrics.data.generate import GeneratorSettings, generate_dataset, main, output_paths, write_all
from molarmetrics.data.schema import TABLE_ORDER


@pytest.fixture(scope="module")
def dataset():
    return generate_dataset(GeneratorSettings())


def test_same_seed_reproduces_identical_tables(dataset):
    again = generate_dataset(GeneratorSettings())
    for table in TABLE_ORDER:
        assert again.tables[table] == dataset.tables[table], table


def test_different_seed_gives_different_data(dataset):
    other = generate_dataset(GeneratorSettings(seed=7))
    assert other.tables["appointments"] != dataset.tables["appointments"]


def test_shipped_csv_files_match_a_fresh_seed_42_generation(tmp_path, real_db_path):
    """The CSVs in data/csv must be exactly what seed 42 produces."""
    paths = write_all(generate_dataset(GeneratorSettings()), tmp_path)
    shipped_dir = real_db_path.parent / "csv"
    for table in TABLE_ORDER:
        fresh = paths[f"csv_{table}"].read_bytes()
        shipped = (shipped_dir / f"molarmetrics_{table}.csv").read_bytes()
        assert hashlib.sha256(fresh).hexdigest() == hashlib.sha256(shipped).hexdigest(), table


def test_requested_sizes(dataset):
    t = dataset.tables
    assert len(t["patients"]) == 1000
    assert len(t["dentists"]) == len(DENTISTS) == 8
    assert 5500 <= len(t["appointments"]) <= 6500  # "approximately 6,000"


def test_no_direct_identifiers_are_generated(dataset):
    assert set(dataset.tables["patients"][0]) == {"patient_id", "birth_year", "gender", "locality",
                                                  "registration_date"}


def test_overwrite_guard(tmp_path, dataset):
    write_all(dataset, tmp_path)
    with pytest.raises(FileExistsError, match="--overwrite"):
        write_all(dataset, tmp_path)
    write_all(dataset, tmp_path, overwrite=True)  # explicit overwrite succeeds
    assert main(["--out-dir", str(tmp_path)]) == 1  # CLI refuses without --overwrite


def test_generated_database_passes_every_validation_check(tmp_path, dataset):
    paths = write_all(dataset, tmp_path)
    report = json.loads(paths["validation_report"].read_text())
    failed = [c["id"] for c in report["checks"] if c["severity"] == "error" and not c["passed"]]
    assert failed == []
    assert report["summary"]["status"] == "PASS"
    assert report["dataset"]["settings"]["seed"] == 42
    for key in ("db", "dictionary_md", "dictionary_csv"):
        assert paths[key].exists()


def test_output_files_use_the_molarmetrics_prefix(tmp_path):
    for path in output_paths(tmp_path).values():
        assert path.name.startswith("molarmetrics")
