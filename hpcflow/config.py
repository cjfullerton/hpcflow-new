import copy
import json
import logging
import os
from re import L
import socket
from typing import Any, Dict, List, Optional, Tuple, Union
import warnings
from pathlib import Path

from ruamel.yaml import YAML
from valida.schema import Schema

from hpcflow import RUN_TIME_INFO
from hpcflow.errors import (
    ConfigChangeInvalidJSONError,
    ConfigChangePopIndexError,
    ConfigChangeTypeInvalidError,
    ConfigChangeValidationError,
    ConfigFileValidationError,
    ConfigUnknownItemError,
    ConfigFileInvocationIncompatibleError,
    ConfigValidationError,
    ConfigChangeInvalidError,
    ConfigChangeFileUpdateError,
)
from hpcflow.utils import Singleton
from hpcflow.validation import get_schema

logger = logging.getLogger(__name__)


class ConfigType(type):
    """Metaclass for the `Config` convenience class that allows access to the
    `ConfigLoader` singleton instance via the `Config` class."""

    def __getattr__(cls, key):
        return getattr(ConfigLoader(), key)

    def __str__(cls):
        return cls.to_string(exclude=["config_file_contents"])

    def to_string(cls, exclude=None):
        return ConfigLoader().to_string(exclude=exclude)

    def __dir__(cls):
        return dir(ConfigLoader())


class Config(metaclass=ConfigType):
    """Convenience class to retrive config values set in the ConfigSetter singleton.

    Methods
    -------
    to_string : get a formatted string
    get_configurable : list all configurable items
    get : get a configuration item
    set_value : set a configuration item
    unset_value : unset a configuration item
    append_value : append a value to a list configuration item
    prepend_value : prepend a value to a list configuration item
    pop_value : pop a value from a list configuration item

    """


class ConfigLoader(metaclass=Singleton):
    """Singleton class used to load the configuration from a YAML file.

    Attributes
    ----------
    _configurable_keys : list
    _meta_data : dict
    _configured_data : dict
    _config_schemas : list of valida.schema.Schema
    _cfg_file_dat_rt : dict

    """

    CONFIG_DIR_ENV_VAR = "HPCFLOW_CONFIG_DIR"
    CONFIG_DIR_DEFAULT = "~/.hpcflow"
    DEFAULT_CONFIG = {
        "machine": socket.gethostname(),
        "defaults": {},
        "configs": {
            "default": {
                "invocation": {"environment_setup": None, "match": {}},
                "config": {
                    "log_directory": "logs",
                    "environment_sources": [],
                    "task_schema_sources": [],
                },
            }
        },
    }

    def __init__(self, config_schema: Schema = None, config_dir=None):
        """
        Parameters
        ----------
        config_schema
            An addition configuration schema to combine with the built-in schema.

        """

        cfg_schemas = [get_schema("config_schema.yaml")]
        if config_schema:
            cfg_schemas.append(config_schema)

        # Get allowed configurable keys from config schemas:
        cfg_keys = []
        for cfg_schema in cfg_schemas:
            for rule in cfg_schema.rules:
                if not rule.path and rule.condition.callable.name == "allowed_keys":
                    cfg_keys.extend(rule.condition.callable.args)

        self._configurable_keys = cfg_keys

        cfg_dir = ConfigLoader._resolve_config_dir(config_dir)
        (
            cfg_file_dat,
            cfg_file_dat_rt,
            cfg_file_path,
            cfg_file_contents,
        ) = ConfigLoader._get_main_config_file(cfg_dir)

        file_schema = get_schema("config_file_schema.yaml")
        file_validated = file_schema.validate(cfg_file_dat)
        if not file_validated.is_valid:
            raise ConfigFileValidationError(file_validated.get_failures_string())

        # select appropriate config data for this invocation using run-time info:
        cfg_inv_data = None
        cfg_inv_key = None
        for c_name_i, c_dat_i in cfg_file_dat["configs"].items():
            is_match = True
            for match_k, match_v in c_dat_i["invocation"]["match"].items():
                if getattr(RUN_TIME_INFO, match_k) != match_v:
                    is_match = False
                    break
            if is_match:
                cfg_inv_data = c_dat_i
                cfg_inv_key = c_name_i
                logger.info(
                    f"Found matching config ({cfg_inv_key!r}) for this invocation."
                )
                break
        if not is_match:
            raise ConfigFileInvocationIncompatibleError()

        self._cfg_file_dat_rt = cfg_file_dat_rt  # round-trippable data from YAML file

        self._meta_data = {
            "config_dir": cfg_dir,
            "config_file_path": cfg_file_path,
            "config_file_contents": cfg_file_contents,
            "config_invocation_key": cfg_inv_key,
            "config_schemas": cfg_schemas,
        }
        self._configured_data = cfg_inv_data["config"]
        self._validate_configured_data(self._configured_data)

    def __dir__(self):
        return super().__dir__() + self._all_keys

    def __str__(self):
        return self.to_string(exclude=["config_file_contents"])

    def __getattr__(self, name):
        if name in self._meta_data:
            return self._meta_data[name]
        elif name in self._configurable_keys:
            return self._configured_data.get(name)
        else:
            raise ConfigUnknownItemError(
                f"Specified name {name!r} is not a valid configuration item."
            )

    @property
    def _all_keys(self):
        return list(self._meta_data.keys()) + self._configurable_keys

    @property
    def _cfg_inv_key(self):
        return self._meta_data["config_invocation_key"]

    def _validate_configured_data(self, data):
        for cfg_schema in self._meta_data["config_schemas"]:
            cfg_validated = cfg_schema.validate(data)
            if not cfg_validated.is_valid:
                raise ConfigValidationError(cfg_validated.get_failures_string())

    @staticmethod
    def _get_main_config_file(config_dir: Path) -> Tuple[Dict, Dict, Path, str]:
        """Load data from the main configuration file (config.yaml or config.yml).

        Parameters
        ----------
        config_dir
            Directory in which to find the configuration file.

        Returns
        -------
        cfg_file_dat : dict
            Data loaded from the config file using the "safe" load
        cfg_file_dat_rt : dict
            Data loaded from the config file using the "round-trip" load.
        cfg_file_path
            Path to the config file.
        cfg_file_contents
            Contents of the config file.

        """

        # Try both ".yml" and ".yaml" extensions:
        cfg_file_path = config_dir.joinpath("config.yaml")
        if not cfg_file_path.is_file():
            cfg_file_path = config_dir.joinpath("config.yml")

        if not cfg_file_path.is_file():
            logger.info(
                "No config.yaml found in the configuration directory. Generating "
                "a config.yaml file."
            )
            yaml = YAML(typ="rt")
            with cfg_file_path.open("w") as handle:
                yaml.dump(ConfigLoader.DEFAULT_CONFIG, handle)

        yaml = YAML(typ="safe")
        yaml_rt = YAML(typ="rt")
        with cfg_file_path.open() as handle:
            cfg_file_contents = handle.read()
            handle.seek(0)
            cfg_file_dat = yaml.load(handle)
            handle.seek(0)
            cfg_file_dat_rt = yaml_rt.load(handle)

        return cfg_file_dat, cfg_file_dat_rt, cfg_file_path, cfg_file_contents

    @staticmethod
    def _resolve_config_dir(config_dir: Optional[Union[str, Path]] = None):
        """Find the directory in which to locate the configuration file.

        If no configuration directory is specified, look first for an environment variable
        (given by `ConfigLoader.CONFIG_DIR_ENV_VAR`), and then in the default configuration
        directory (given by `ConfigLoader.CONFIG_DIR_DEFAULT`).

        The configuration directory will be created if it does not exist.

        Parameters
        ----------
        config_dir
            Directory in which to find the configuration file. Optional.

        Returns
        -------
        config_dir : Path
            Absolute path to the configuration directory.

        """

        if not config_dir:
            config_dir = Path(
                os.getenv(
                    ConfigLoader.CONFIG_DIR_ENV_VAR, ConfigLoader.CONFIG_DIR_DEFAULT
                )
            ).expanduser()
        else:
            config_dir = Path(config_dir)

        if not config_dir.is_dir():
            logger.info(
                f"Configuration directory does not exist. Generating here: {str(config_dir)!r}."
            )
            config_dir.mkdir()
        else:
            logger.info(f"Using configuration directory: {str(config_dir)!r}.")

        return config_dir.absolute()

    def _update_config_file(self):
        """Overwrite the config file with a new file from the stored configuration
        information."""

        # write a new temporary config file
        cfg_file_path = self._meta_data["config_file_path"]
        cfg_tmp_file = cfg_file_path.with_suffix(".tmp")
        logger.info(f"Creating temporary config file: {cfg_tmp_file!r}.")
        yaml = YAML(typ="rt")
        with cfg_tmp_file.open("w") as fh:
            yaml.dump(self._cfg_file_dat_rt, fh)

        # atomic rename, overwriting original:
        logger.info("Replacing original config file with temporary file.")
        os.replace(src=cfg_tmp_file, dst=cfg_file_path)

    def _modify_if_valid(self, name: str, new_value: Any = None, is_unset: bool = False):
        """Try to modify the configuration, both in-memory and in the YAML file.

        Parameters
        ----------
        name
            name of configuration item to modify
        new_value
            The new value to update a configuration item to, if updating an item. Only
            applicable if `is_unset` is False.
        is_unset
            Set to True when we want to remove the value of a configuration item. Only
            applicable if `new_value` is None

        Returns
        -------
        new_value if `new_value` was passed or True if not

        """

        # validate change:
        dat_copy = copy.deepcopy(self._configured_data)
        old_value = dat_copy[name]
        if is_unset:
            del dat_copy[name]
        else:
            dat_copy[name] = new_value
        try:
            self._validate_configured_data(dat_copy)
        except ConfigValidationError as err:
            raise ConfigChangeValidationError(name, validation_err=err)

        # update object attributes:
        if is_unset:
            del self._cfg_file_dat_rt["configs"][self._cfg_inv_key]["config"][name]
            del self._configured_data[name]
        else:
            self._cfg_file_dat_rt["configs"][self._cfg_inv_key]["config"][
                name
            ] = new_value
            self._configured_data[name] = new_value

        try:
            # update config file:
            self._update_config_file()

        except Exception as err:
            # reinstate old value:
            self._cfg_file_dat_rt["configs"][self._cfg_inv_key]["config"][
                name
            ] = old_value
            self._configured_data[name] = old_value

            raise ConfigChangeFileUpdateError(name, err=err)

        if is_unset:
            logger.info(f"Unset config item {name!r}.")
            return True
        else:
            logger.info(
                f"Updated config item {name!r} from value {old_value!r} to value "
                f"{new_value!r}."
            )
            return new_value

    def _set_value(self, name, old_value, new_value):
        """Set a configuration item from its `old_value` to its `new_value`."""

        if old_value == new_value:
            warnings.warn(f"Config key {name!r} is already set to value {new_value!r}.")
            return

        return self._modify_if_valid(name, new_value=new_value)

    def _unset_value(self, name):
        """Unset (remove) a configuration item."""

        if name not in self._configured_data:
            warnings.warn(f"Config key {name!r} is already not set.")
            return

        return self._modify_if_valid(name, is_unset=True)

    def _prepare_modify(self, name: str, new_value: Any = None, is_json: bool = False):
        """Prepare for the modification of a named configuration item.

        Parameters
        ----------
        name
            Name of the configuration item that is to be modified.
        new_value
            New value as passed from the user.
        is_json
            If True, interpret `new_value` as a JSON string and load it using the json
            library.

        Returns
        -------
        old_value
            A copy of the configuration item value that is to be modified.
        new_value
            If `is_json` is true, this is the JSON-decoded-`new_value`. Otherwise, this is
            just `new_value` passed back.

        """

        if name not in self._configurable_keys:
            raise ConfigChangeInvalidError(name=name)

        if is_json:
            try:
                new_value = json.loads(new_value)
            except json.decoder.JSONDecodeError as err:
                raise ConfigChangeInvalidJSONError(name=name, json_str=new_value, err=err)

        old_value = copy.deepcopy(self.get(name))

        return old_value, new_value

    def to_string(self, exclude: Optional[List] = None):
        """Format the instance in a string, optionally exclude some keys.

        Parameters
        ----------
        exclude
            List of keys to exclude. Optional.

        """
        exclude = exclude or []
        lines = []
        blocks = {"meta-data": self._meta_data, "configuration": self._configured_data}
        for title, dat in blocks.items():
            lines.append(f"{title}:")
            for key, val in dat.items():
                if key in exclude:
                    continue
                lines.append(f"  {key}: {val}")
        return "\n".join(lines)

    def get_configurable(self):
        """Get a list of all configurable keys."""
        return self._configurable_keys

    def get(self, name: str):
        """Get a configuration item.

        Parameters
        ----------
        name
            The name of a configuration item (either a configurable key or a meta-data key)

        Returns
        -------
        The value of the specified configuration item.

        """

        return getattr(self, name)

    def set_value(self, name: str, value: Any, is_json: bool):
        """Set the value of a configuration item.

        Parameters
        ----------
        name
            The name of a configurable configuration item to set.
        value
            The value to set the configuration item to.
        is_json
            If True, `value` will first be JSON-decoded.

        Returns
        -------
        new_value
            The new value that has been set.

        """

        old_value, new_value = self._prepare_modify(name, value, is_json)
        return self._set_value(name, old_value, new_value)

    def unset_value(self, name: str):
        """Unset (remove) the value of a configuration item.

        Parameters
        ----------
        name
            The name of a configurable configuration item to unset.

        Returns
        -------
        True

        """

        self._prepare_modify(name)
        return self._unset_value(name)

    def append_value(self, name, value, is_json):
        """Append a new value to an existing configuration list item.

        Parameters
        ----------
        name
            The name of a configurable configuration item to modify.
        value
            The value to append to the configuration item.
        is_json
            If True, `value` will first be JSON-decoded.

        Returns
        -------
        new_value
            The new value that has been modified.

        """

        old_value, new_value = self._prepare_modify(name, value, is_json)
        try:
            new_value = old_value + [new_value]
        except TypeError:
            raise ConfigChangeTypeInvalidError(name, typ=type(old_value))
        return self._set_value(name, old_value, new_value)

    def prepend_value(self, name, value, is_json):
        """Prepend a new value to an existing configuration list item.

        Parameters
        ----------
        name
            The name of a configurable configuration item to modify.
        value
            The value to prepend to the configuration item.
        is_json
            If True, `value` will first be JSON-decoded.

        Returns
        -------
        new_value
            The new value that has been modified.

        """

        old_value, new_value = self._prepare_modify(name, value, is_json)
        try:
            new_value = [new_value] + old_value
        except TypeError:
            raise ConfigChangeTypeInvalidError(name, typ=type(old_value))
        return self._set_value(name, old_value, new_value)

    def pop_value(self, name: str, index: int):
        """Pop (remove) an item from an existing configuration list item.

        Parameters
        ----------
        name
            The name of a configurable configuration item to modify.
        index
            The integer index (zero-based) of the item to remove.

        Returns
        -------
        new_value
            The new value that has been modified.

        """

        old_value, _ = self._prepare_modify(name)
        try:
            new_value = copy.deepcopy(old_value)
            new_value.pop(index)
        except AttributeError:
            raise ConfigChangeTypeInvalidError(name, typ=type(old_value))
        except IndexError:
            raise ConfigChangePopIndexError(name, length=len(old_value), index=index)
        return self._set_value(name, old_value, new_value)
