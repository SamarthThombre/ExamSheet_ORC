import argparse
import xml.etree.ElementTree as ET
from pathlib import Path

LABEL_MAP = {
    "Enrolment_no": "enrolment_no",
    "Enrolment no": "enrolment_no",
    "enrolment_no": "enrolment_no",
    "subject_code": "subject_code",
    "Subject_code": "subject_code",
    "grand_total": "grand_total",
}
CLASS_INDEX = {
    "enrolment_no": 0,
    "subject_code": 1,
    "grand_total": 2,
}


def convert_xml_to_yolo(xml_path: Path) -> str:
    tree = ET.parse(xml_path)
    root = tree.getroot()
    img_w = float(root.findtext("./size/width") or 1)
    img_h = float(root.findtext("./size/height") or 1)

    lines = []
    for obj in root.findall("object"):
        name = (obj.findtext("name") or "").strip()
        if not name:
            continue
        key = LABEL_MAP.get(name, name.lower().replace(" ", "_"))
        if key not in CLASS_INDEX:
            continue
        bbox = obj.find("bndbox")
        if bbox is None:
            continue
        x1 = float(bbox.findtext("xmin", default="0"))
        y1 = float(bbox.findtext("ymin", default="0"))
        x2 = float(bbox.findtext("xmax", default="0"))
        y2 = float(bbox.findtext("ymax", default="0"))

        xc = (x1 + x2) / (2 * img_w)
        yc = (y1 + y2) / (2 * img_h)
        w = max((x2 - x1) / img_w, 1e-6)
        h = max((y2 - y1) / img_h, 1e-6)
        lines.append(f"{CLASS_INDEX[key]} {xc:.6f} {yc:.6f} {w:.6f} {h:.6f}")

    if not lines:
        return ""
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", default="raw_labels", help="folder containing LabelImg XML files")
    args = ap.parse_args()

    project_root = Path(__file__).resolve().parent
    labels_dir = (project_root / args.labels).resolve()
    xml_files = sorted(labels_dir.glob("*.xml"))
    converted = 0
    for xml_file in xml_files:
        txt_content = convert_xml_to_yolo(xml_file)
        if txt_content:
            txt_path = xml_file.with_suffix(".txt")
            txt_path.write_text(txt_content, encoding="utf-8")
            converted += 1
    print(f"Converted {converted} XML files to YOLO text labels in {labels_dir}.")
