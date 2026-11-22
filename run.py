from pathlib import Path

import uvicorn
from alembic import command
from alembic.config import Config
from pydantic import ValidationError

from keitaro_wrapper.config import Settings
from keitaro_wrapper.web import create_app


def main() -> None:
    try:
        settings = Settings()
    except ValidationError as error:
        for item in error.errors(include_input=False, include_context=False, include_url=False):
            print(f"{'.'.join(map(str, item['loc']))}: {item['msg']}")
        raise SystemExit(2) from None

    config = Config(str(Path(__file__).with_name("alembic.ini")))
    config.attributes["database_url"] = settings.database_url
    command.upgrade(config, "head")
    uvicorn.run(create_app(settings), host="127.0.0.1", port=8000, workers=1)


if __name__ == "__main__":
    main()
