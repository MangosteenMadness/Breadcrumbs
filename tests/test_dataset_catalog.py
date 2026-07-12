import tempfile
import unittest
from pathlib import Path

from ingestion.store import (
    connect,
    parse_available_tables,
    parse_dataset_columns,
    parse_dataset_overview,
    upsert_dataset,
    upsert_dataset_columns,
)

# Real text copy/pasted from https://k.owkin.com/explore-data/patient-data/MOSAIC_WINDOW.
# Note the inconsistent blank-line spacing (e.g. no blank line between "MOSAIC WINDOW" and
# "Source") — that inconsistency is exactly what parse_dataset_overview is written to survive.
OVERVIEW_TEXT = """Name

MOSAIC WINDOW
Source

Owkin
Access

Access granted

Total patients

100

Total samples

100

Description

MOSAIC Window is a curated, publicly accessible subset of the MOSAIC dataset, available through Owkin K-Pro Free and via the EGA (European Genome-phenome Archive). It comprises multimodal data, including spatial transcriptomics, from 100 cancer patients across 8 tumor types.

Indications

DLBCL: Diffuse Large B-cell Lymphoma
"""

TABLES_LIST_TEXT = """MOSAIC WINDOW
Name

MOSAIC WINDOW
Source

Owkin
Access

Access granted

Total patients

100

Total samples

100

Available tables

clinical_data_table

120 columns

bkrnaseq_count_table

2 columns

wes_table

5 columns
"""

# The column grid for clinical_data_table, truncated exactly as it arrived mid-paste — the
# trailing "has_received_chemotherapy" / "—" pair is a partial group (2 of 4 values) and
# should be dropped rather than fabricated into a record.
COLUMNS_TEXT = """Column Name

Possible values

Data Type

Completeness

dataset_name

mosaic

category

100.0 %

condition_name

head_and_neck_squamous_cell_carcinoma, diffuse_large_b_cell_lymphoma, non_small_cell_lung_cancer

category

100.0 %

alcohol_quantity_grams_per_day

7.00 – 100.00

float

28.6 %

age

21.00 – 89.00

float

100.0 %

has_received_immunotherapy

—

bool

100.0 %

has_received_chemotherapy

—
"""


class DatasetCatalogTests(unittest.TestCase):
    def test_parses_overview_despite_inconsistent_blank_lines(self):
        overview = parse_dataset_overview(OVERVIEW_TEXT)
        self.assertEqual(overview["name"], "MOSAIC WINDOW")
        self.assertEqual(overview["source"], "Owkin")
        self.assertEqual(overview["total_patients"], 100)
        self.assertEqual(overview["total_samples"], 100)
        self.assertTrue(overview["description"].startswith("MOSAIC Window is a curated"))
        self.assertNotIn("Indications", overview["description"])

    def test_parses_overview_with_comma_formatted_patient_counts(self):
        # Real TCGA capture: "10,372" patients — thousands-separated, unlike MOSAIC's "100".
        overview = parse_dataset_overview(
            "Name\n\nTCGA\nSource\n\nPublic DB\nAccess\n\nAccess granted\n\n"
            "Total patients\n\n10,372\n\nTotal samples\n\n8,867\n\nAvailable tables\n\n"
        )
        self.assertEqual(overview["total_patients"], 10372)
        self.assertEqual(overview["total_samples"], 8867)

    def test_parses_available_tables_list(self):
        tables = parse_available_tables(TABLES_LIST_TEXT)
        self.assertEqual(tables, {
            "clinical_data_table": 120,
            "bkrnaseq_count_table": 2,
            "wes_table": 5,
        })

    def test_parses_column_grid_and_drops_trailing_partial_group(self):
        columns = parse_dataset_columns(COLUMNS_TEXT)
        self.assertEqual(len(columns), 5)
        self.assertNotIn("has_received_chemotherapy", [c["column_name"] for c in columns])

        by_name = {c["column_name"]: c for c in columns}
        self.assertEqual(by_name["dataset_name"], {
            "column_name": "dataset_name",
            "possible_values": "mosaic",
            "data_type": "category",
            "completeness_pct": 100.0,
        })
        self.assertEqual(by_name["alcohol_quantity_grams_per_day"]["completeness_pct"], 28.6)
        self.assertIsNone(by_name["has_received_immunotherapy"]["possible_values"])

    def test_upsert_round_trip_replaces_only_the_named_table(self):
        with tempfile.TemporaryDirectory() as directory:
            connection = connect(Path(directory) / "breadcrumbs.db")
            upsert_dataset(
                connection,
                dataset_id="mosaic_window",
                name="MOSAIC WINDOW",
                url="https://k.owkin.com/explore-data/patient-data/MOSAIC_WINDOW",
                source="Owkin",
                total_patients=100,
                total_samples=100,
            )
            upsert_dataset_columns(
                connection,
                dataset_id="mosaic_window",
                table_name="clinical_data_table",
                columns=parse_dataset_columns(COLUMNS_TEXT),
            )
            upsert_dataset_columns(
                connection,
                dataset_id="mosaic_window",
                table_name="wes_table",
                columns=[{"column_name": "gene", "possible_values": None, "data_type": "category", "completeness_pct": 100.0}],
            )
            # Re-ingesting clinical_data_table with a shorter grid must not touch wes_table.
            upsert_dataset_columns(
                connection,
                dataset_id="mosaic_window",
                table_name="clinical_data_table",
                columns=[{"column_name": "age", "possible_values": "21.00 - 89.00", "data_type": "float", "completeness_pct": 100.0}],
            )
            rows = connection.execute(
                "SELECT table_name, column_name FROM dataset_columns ORDER BY table_name, column_name"
            ).fetchall()
            self.assertEqual(
                [(row["table_name"], row["column_name"]) for row in rows],
                [("clinical_data_table", "age"), ("wes_table", "gene")],
            )
            connection.close()


if __name__ == "__main__":
    unittest.main()
