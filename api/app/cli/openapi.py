"""Print the OpenAPI schema as JSON (make types feeds it to openapi-typescript).

No database is needed: the schema comes from the route and model definitions.
"""

import json
import os
import sys

os.environ.setdefault("SERVE_FILES", "false")

from app.main import create_app


def main() -> None:
    schema = create_app().openapi()
    json.dump(schema, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
