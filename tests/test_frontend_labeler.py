import csv

import pytest

from frontend.serve import DATASETS, read_label_records, save_mark_record, validate_mark_values


def test_v4_dataset_uses_separate_images_and_labels():
    assert DATASETS["v4"]["images_dir"].as_posix().endswith("data/data_v4/images")
    assert DATASETS["v4"]["labels_csv"].name == "canonical_labels_v4.csv"
    assert DATASETS["v4"]["enrollment_prefix"] == "0801CA25"
    assert DATASETS["v4"]["subject_code"] == "CT10222"


def test_read_label_records_prefills_legacy_total(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    (images / "page_000001.png").write_bytes(b"image")
    labels = tmp_path / "canonical_labels.csv"
    labels.write_text(
        "image_filename,enrollment_no,subject_code,total_marks,sheet_no,status\n"
        "page_000001.png,0801CA251001,CT10718,54,1,verified\n",
        encoding="utf-8",
    )

    items, _ = read_label_records(labels, images)

    assert len(items) == 1
    assert items[0]["grand_total"] == "54"
    assert items[0]["enrollment_no"] == "0801CA251001"
    assert items[0]["q1"] == ""
    assert items[0]["marks_status"] == ""


def test_save_mark_record_keeps_legacy_fields_and_syncs_total(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    (images / "page_000001.png").write_bytes(b"image")
    labels = tmp_path / "canonical_labels.csv"
    labels.write_text(
        "image_filename,enrollment_no,subject_code,total_marks,sheet_no,status\n"
        "page_000001.png,0801CA251001,CT10718,54,1,verified\n",
        encoding="utf-8",
    )

    row = save_mark_record(
        "page_000001.png",
        {"q1": "11", "q2": "12.5", "q3": "", "q4": "9", "q5": "10", "grand_total": "54"},
        labels,
        images,
    )

    assert row["total_marks"] == "54"
    assert row["marks_status"] == "verified"
    with labels.open(newline="", encoding="utf-8") as csv_file:
        saved = next(csv.DictReader(csv_file))
    assert saved["enrollment_no"] == "0801CA251001"
    assert saved["sheet_no"] == "1"
    assert saved["q2"] == "12.5"
    assert saved["grand_total"] == "54"


def test_save_mark_record_creates_v2_style_dataset_row(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    (images / "page_000001.png").write_bytes(b"image")
    labels = tmp_path / "canonical_labels_v3.csv"

    row = save_mark_record(
        "page_000001.png",
        {
            "enrollment_no": "1001",
            "subject_code": "CT10715",
            "q1": "2.5+0.5",
            "grand_total": "3",
        },
        labels,
        images,
        "0801CA25",
    )

    assert row["enrollment_no"] == "0801CA251001"
    assert row["subject_code"] == "CT10715"
    assert row["q1"] == "3"
    assert row["grand_total"] == "3"
    assert "total_marks" not in row
    with labels.open(newline="", encoding="utf-8") as csv_file:
        saved = next(csv.DictReader(csv_file))
    assert saved["marks_status"] == "verified"


def test_save_mark_record_requires_four_digit_suffix_for_v3(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    (images / "page_000001.png").write_bytes(b"image")

    with pytest.raises(ValueError, match="four digits"):
        save_mark_record(
            "page_000001.png",
            {
                "enrollment_no": "10001",
                "subject_code": "CT10716",
                "grand_total": "3",
            },
            tmp_path / "canonical_labels_v3.csv",
            images,
            "0801CA25",
        )


def test_validate_mark_values_evaluates_addition_for_question_and_total():
    values = validate_mark_values({
        "q1": "2.5+0.5",
        "q2": "",
        "grand_total": "2.5 + 0.5",
    })

    assert values["q1"] == "3"
    assert values["q2"] == ""
    assert values["grand_total"] == "3"


@pytest.mark.parametrize("value", ["", "-1", "71", "not-a-mark"])
def test_validate_mark_values_rejects_invalid_total(value):
    with pytest.raises(ValueError):
        validate_mark_values({"grand_total": value})


@pytest.mark.parametrize("value", ["2.5+", "+0.5", "2.5*0.5", "70+0.5"])
def test_validate_mark_values_rejects_invalid_or_out_of_range_addition(value):
    with pytest.raises(ValueError):
        validate_mark_values({"grand_total": value})
