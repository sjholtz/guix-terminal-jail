import logging
import os
from dataclasses import dataclass
from pathlib import Path

import tomllib
from dotenv import dotenv_values
from mitmproxy import http

# The launcher timestamps the entire mitmdump stream, including addon records.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.propagate = False
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("[KeyInjector] %(levelname)s %(message)s"))
logger.handlers[:] = [handler]


@dataclass(frozen=True)
class HeaderMapping:
    host: str
    environment_variable: str


def load_header_mappings(
    config_path: Path,
) -> dict[str, list[HeaderMapping]]:
    try:
        with config_path.open("rb") as config_file:
            configuration = tomllib.load(config_file)
    except FileNotFoundError:
        logger.critical(f"Header configuration not found: {config_path}")
        raise
    except OSError as error:
        logger.critical(f"Could not read header configuration {config_path}: {error}")
        raise
    except tomllib.TOMLDecodeError as error:
        logger.critical(f"Invalid TOML configuration {config_path}: {error}")
        raise

    mappings: dict[str, list[HeaderMapping]] = {}

    for section_name in ("auth", "x-api"):
        section = configuration.get(section_name, {})
        entries = section.get("headers", [])

        if not isinstance(entries, list):
            raise TypeError(f"'{section_name}.headers' must be an array of tables")

        mappings[section_name] = []

        for entry in entries:
            if not isinstance(entry, dict):
                raise TypeError(f"Entries in '{section_name}.headers' must be a table")

            host = entry.get("host")
            environment_variable = entry.get("environment_variable")

            if not isinstance(host, str) or not host:
                raise TypeError(f"Entries in '{section_name}.headers' require a host")
            if not isinstance(environment_variable, str) or not environment_variable:
                raise TypeError(
                    f"Entries in '{section_name}.headers' require an "
                    "environment_variable"
                )

            mappings[section_name].append(
                HeaderMapping(
                    host=host,
                    environment_variable=environment_variable,
                )
            )

    return mappings


class KeyInjector:
    def __init__(self) -> None:
        credentials_path = Path(os.environ["GUIX_JAIL_CREDENTIALS"])
        with credentials_path.open(encoding="utf-8") as credentials:
            self.credentials = dotenv_values(stream=credentials, interpolate=False)
        configured_path = os.getenv("KEY_INJECTOR_CONFIG") or self.credentials.get(
            "KEY_INJECTOR_CONFIG"
        )
        self.config_path = (
            Path(configured_path).expanduser()
            if configured_path
            else Path(os.environ["GUIX_JAIL_CONFIG_DIR"]) / "key-injector.toml"
        )
        logger.info("Loading credentials from %s", credentials_path)
        self.mappings = load_header_mappings(self.config_path)

    def _find_mapping(
        self,
        host: str,
        mappings: list[HeaderMapping],
    ) -> HeaderMapping | None:
        for mapping in mappings:
            # API keys are destination-specific: do not implicitly trust subdomains.
            if host == mapping.host.lower().rstrip("."):
                return mapping

        logger.debug(f"No header mapping matched host: {host}")
        return None

    def _inject_header(
        self,
        flow: http.HTTPFlow,
        host: str,
        header_name: str,
        mappings: list[HeaderMapping],
    ) -> None:
        mapping = self._find_mapping(host, mappings)

        if not mapping:
            return

        key = self.credentials.get(mapping.environment_variable)

        if not key:
            logger.warning(
                f"{mapping.environment_variable} is not set; could not "
                f"inject {header_name} for {host}"
            )
            return

        prefix = "Bearer " if header_name == "Authorization" else ""
        flow.request.headers[header_name] = f"{prefix}{key}"
        logger.info(f"Injected {mapping.environment_variable} into {header_name}")

    def request(self, flow: http.HTTPFlow) -> None:
        if flow.request.scheme != "https" or flow.request.port != 443:
            return

        host = flow.request.host.lower().rstrip(".")
        logger.info(f"Intercepted request to: {host}")

        self._inject_header(
            flow,
            host,
            "Authorization",
            self.mappings["auth"],
        )

        self._inject_header(
            flow,
            host,
            "x-api-key",
            self.mappings["x-api"],
        )


addons = [KeyInjector()]
