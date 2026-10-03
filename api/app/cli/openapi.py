"""Print the OpenAPI schema as JSON (make types feeds it to openapi-typescript).

No database and no real secrets are needed: the schema comes from the route and model
definitions, so it's built with throwaway keys.
"""

import json
import sys

from app.cli import offline_settings
from app.main import create_app


def main() -> None:
    schema = create_app(offline_settings()).openapi()
    json.dump(schema, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
