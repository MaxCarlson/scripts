# folder_util/reporter.py

import json
import csv

def export_json(items, filename):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(items, f, default=str, indent=4)

def export_csv(items, filename, columns):
    with open(filename, "w", newline='', encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        header = ["Name"] + [col.capitalize().replace("_", " ") for col in columns]
        writer.writerow(header)
        for item in items:
            row = [item.get("name", "")]
            for col in columns:
                if col in ["date_created", "date_modified", "date_accessed"]:
                    dt = item.get(col)
                    value = dt.strftime("%Y-%m-%d %H:%M") if dt else ""
                else:
                    value = item.get(col, "")
                row.append(value)
            writer.writerow(row)

def export_text(items, filename, columns, truncate=20):
    with open(filename, "w", encoding="utf-8") as f:
        header = ["Name"] + [col.capitalize().replace("_", " ") for col in columns]
        col_widths = [max(len(h), truncate) for h in header]
        header_line = " | ".join(h.ljust(w) for h, w in zip(header, col_widths))
        f.write(header_line + "\n")
        f.write("-" * len(header_line) + "\n")
        for item in items:
            name = item.get("name", "")
            if len(name) > truncate:
                name = name[:truncate] + "..."
            row = [name]
            for col in columns:
                if col in ["date_created", "date_modified", "date_accessed"]:
                    dt = item.get(col)
                    value = dt.strftime("%Y-%m-%d %H:%M") if dt else ""
                else:
                    value = str(item.get(col, ""))
                row.append(value)
            line = " | ".join(str(val).ljust(w) for val, w in zip(row, col_widths))
            f.write(line + "\n")