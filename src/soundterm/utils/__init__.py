from typing import Any
from datetime import datetime
from uuid import UUID


def flatten(
    to_flatten: Any, prefix: str | None = None
) -> dict[str, str | list[str] | datetime | None]:
    if not prefix:
        prefix = to_flatten.__class__.__name__.lower()
    attr_dict = {}
    flatten_dict: dict[str, Any] = {}

    if isinstance(to_flatten, list):
        for idx, item in enumerate(to_flatten):
            if hasattr(item, "flatten"):
                attr_dict[f"{prefix}_{idx}"] = flatten(item, prefix=f"{prefix}_{idx}")
            else:
                attr_dict[f"{prefix}_{idx}"] = str(item)
        attr_dict[prefix] = [str(v) for v in to_flatten]
        return attr_dict

    elif hasattr(to_flatten, "model_dump"):
        flatten_dict = to_flatten.model_dump()
    elif isinstance(to_flatten, dict):
        flatten_dict = to_flatten
    else:
        attr_dict[prefix] = to_flatten
        return attr_dict

    for key, value in flatten_dict.items():
        new_key = f"{prefix}_{key}"
        if isinstance(value, list):
            for idx, item in enumerate(value):
                if hasattr(item, "flatten"):
                    attr_dict[f"{new_key}_{idx}"] = flatten(
                        item, prefix=f"{new_key}_{idx}"
                    )
                else:
                    attr_dict[f"{new_key}_{idx}"] = str(item)
            attr_dict[new_key] = [str(v) for v in value]
        elif isinstance(value, datetime):
            attr_dict[new_key] = value.isoformat()
        elif isinstance(value, UUID):
            attr_dict[new_key] = str(value)
        else:
            attr_dict[new_key] = value

    return attr_dict


if __name__ == "__main__":
    test = {
        "id": UUID("12345678-1234-5678-1234-567812345678"),
        "name": "Test Object",
        "created_at": datetime(2024, 6, 1, 12, 0, 0),
        "items": [
            {"item_id": 1, "value": "First"},
            {"item_id": 2, "value": "Second"},
        ],
    }
    flattened = flatten(test)
    for key, value in flattened.items():
        print(f"{key}: {value}")
