"""Build data/shelf_life.json from a downloaded USDA FoodKeeper JSON file.

Usage:
    python scripts/import_foodkeeper.py [path/to/foodkeeper.json]

Source: USDA FSIS FoodKeeper (public domain, CC0), listed on data.gov at
https://catalog.data.gov/dataset/fsis-foodkeeper-data
"""

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core.foodkeeper import data_version, derive_category_defaults, parse_products  # noqa: E402

DEFAULT_INPUT = ROOT / "data" / "raw" / "foodkeeper.json"
OUTPUT = ROOT / "data" / "shelf_life.json"
SOURCE_URL = "https://www.fsis.usda.gov/shared/data/EN/foodkeeper.json"
RETRIEVED_FROM = (
    "https://web.archive.org/web/20250702182320/"
    "https://www.fsis.usda.gov/shared/data/EN/foodkeeper.json"
)


def main() -> None:
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_INPUT
    raw = input_path.read_bytes()
    doc = json.loads(raw.decode("utf-8"))

    products = parse_products(doc)
    defaults = derive_category_defaults(products)

    output = {
        "source": {
            "name": "USDA FSIS FoodKeeper",
            "license": "CC0 (public domain)",
            "url": SOURCE_URL,
            "retrieved_from": RETRIEVED_FROM,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "data_version": data_version(doc),
        },
        "products": [p.model_dump(mode="json", exclude_defaults=True) for p in products],
        "category_defaults": [d.model_dump(mode="json") for d in defaults],
    }
    OUTPUT.write_text(json.dumps(output, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(products)} products and {len(defaults)} category defaults to {OUTPUT}")


if __name__ == "__main__":
    main()
