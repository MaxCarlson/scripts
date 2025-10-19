
import pathlib
from typing import List

import yaml
from pydantic import ValidationError

from .models import Host

CONFIG_PATH = pathlib.Path.home() / ".config" / "syncmux" / "config.yml"


def load_config() -> List[Host]:
    """Loads the configuration file and returns a list of Host objects."""
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Configuration file not found at: {CONFIG_PATH}")

    with open(CONFIG_PATH, "r") as f:
        try:
            config_data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise yaml.YAMLError(f"Error parsing YAML file: {e}")

    try:
        return [Host(**host) for host in config_data["hosts"]]
    except (ValidationError, KeyError) as e:
        raise ValidationError(f"Invalid configuration: {e}")


def save_config(hosts: List[Host]) -> None:
    """Saves the list of Host objects to the configuration file."""
    # Ensure directory exists
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Convert hosts to dict format
    config_data = {
        "hosts": [host.model_dump(exclude_none=True) for host in hosts]
    }

    # Write to file
    with open(CONFIG_PATH, "w") as f:
        yaml.safe_dump(config_data, f, default_flow_style=False, sort_keys=False)
