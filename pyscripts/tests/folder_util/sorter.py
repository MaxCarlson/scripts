# folder_util/sorter.py

def sort_items(items, sort_key="date", reverse=True):
    if sort_key == "name":
        return sorted(items, key=lambda x: x.get("name", "").lower(), reverse=reverse)
    elif sort_key == "size":
        return sorted(items, key=lambda x: x.get("size", 0), reverse=reverse)
    elif sort_key == "date":
        return sorted(items, key=lambda x: x.get("date_created"), reverse=reverse)
    else:
        return sorted(items, key=lambda x: x.get("name", "").lower(), reverse=reverse)