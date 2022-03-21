from dataclasses import dataclass
import logging
from typing import Optional

import click

from hpcflow import __version__, log
from hpcflow.cli import cli
from hpcflow.app_log import AppLog


@dataclass
class HPCFlowApp:
    """Class for instantiating an HPCFlow application, which may provide, for instance,
    custom parameter logic, over the top of that provided by hpcflow."""

    name: str
    version: str
    description: Optional[str] = None

    def __post_init__(self):
        self.CLI = self.make_CLI()
        self.description = self.description or self.name
        self.log = AppLog(self.name, hpcflow_app_log=log)

    def make_CLI(self):
        def new_CLI(console_log_level, file_log_level, file_log_path=None):
            self.log.update_handlers(console_log_level, file_log_level, file_log_path)

        new_CLI.__doc__ = self.description

        new_CLI = click.version_option(
            package_name=self.name, prog_name=self.name, version=self.version
        )(new_CLI)

        new_CLI = click.option(
            "--console-log-level",
            type=click.Choice(list(logging._levelToName.values()), case_sensitive=False),
            help="Set console log level",
        )(new_CLI)

        new_CLI = click.option(
            "--file-log-level",
            type=click.Choice(list(logging._levelToName.values()), case_sensitive=False),
            help="Set console log level",
        )(new_CLI)

        new_CLI = click.option("--file-log-path", help="Set file log path")(new_CLI)

        new_CLI = click.version_option(
            __version__, "--hpcflow-version", package_name="hpcflow", prog_name="hpcflow"
        )(new_CLI)

        new_CLI = click.group(name=self.name)(new_CLI)

        for name, command in cli.commands.items():
            # add each hpcflow command as a new CLI command:
            new_CLI.add_command(command, name=name)
        return new_CLI
