"""Start PlunderBot. Exocomp runs this file; locally, `python bot.py` with a .env loaded."""
from __future__ import annotations

import logging
import sys

from exocomp_telemetry import Telemetry
from plunderbot import __version__, config
from plunderbot.bot import PlunderBot


def main() -> None:
    cfg = config.load()
    level = cfg.log_level if cfg.log_level in logging.getLevelNamesMapping() else "INFO"
    logging.basicConfig(level=level, stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg.ready_file.unlink(missing_ok=True)  # a restart must reconnect before it counts as healthy
    telemetry = Telemetry(version=__version__)
    bot = PlunderBot(cfg, telemetry=telemetry)
    telemetry.attach(bot)
    logging.getLogger("discord").addHandler(telemetry.log_handler())
    bot.run(cfg.discord_token, log_handler=None)


if __name__ == "__main__":
    main()
