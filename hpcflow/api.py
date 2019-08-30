"""`hpcflow.api.py`

This module contains the application programming interface (API) to `hpcflow`,
and includes functions that are called by the command line interface (CLI; in
`hpcflow.cli.py`).

"""

from pathlib import Path
from pprint import pprint
import json

from beautifultable import BeautifulTable

from hpcflow import CONFIG, profiles
from hpcflow.init_db import init_db
from hpcflow.models import Workflow, Submission, CommandGroupSubmission
from hpcflow.profiles import parse_job_profiles
from hpcflow.project import Project


def make_workflow(dir_path=None, profile_list=None, json_file=None,
                  json_str=None, clean=False):
    """Generate a new Workflow and add it to the local database.

    Parameters
    ----------
    dir_path : str or Path, optional
        The directory in which the Workflow will be generated. By default, this
        is the working (i.e. invoking) directory.
    profile_list : list of (str or Path), optional
        List of YAML profile file paths to use to construct the Workflow. By
        default, and if `json_file` and `json_str` and not specified, all
        YAML files in the `dir_path` directory that match the profile
        specification format in the global configuration will be parsed as
        Workflow profiles. If not None, only those profiles listed will be
        parsed as Workflow profiles.
    json_file : str or Path, optional
        Path to a JSON file that represents a Workflow. By default, set to
        `None`.
    json_str : str, optional
        JSON string that represents a Workflow. By default, set to `None`.
    clean : bool, optional
        If True, all existing hpcflow data will be removed from `dir_path`.
        Useful for debugging.

    Returns
    -------
    workflow_id : int
        The insert ID of the Workflow object in the local database.

    Notes
    -----
    Specify only one of `profile_list`, `json_file` or `json_str`.

    """

    not_nones = sum(
        [i is not None for i in [profile_list, json_file, json_str]])
    if not_nones > 1:
        msg = ('Specify only one of `profile_list`, `json_file` or `json_str`.')
        raise ValueError(msg)

    project = Project(dir_path, clean=clean)

    if json_str:
        workflow_dict = json.loads(json_str)

    elif json_file:
        with Path(json_file).open() as handle:
            workflow_dict = json.load(handle)

    else:
        # Get workflow from YAML profiles:
        workflow_dict = parse_job_profiles(project.dir_path, profile_list)

    Session = init_db(project, check_exists=False)
    session = Session()

    workflow = Workflow(directory=project.dir_path, **workflow_dict)

    session.add(workflow)
    session.commit()

    workflow_id = workflow.id_
    session.close()

    return workflow_id


def submit_workflow(workflow_id, dir_path=None, task_ranges=None):
    """Submit (part of) a previously generated Workflow.

    Parameters
    ----------
    workflow_id : int
        The ID of the Workflow to submit, as in the local database.
    dir_path : str or Path, optional
        The directory in which the Workflow exists. By default, this is the
        working (i.e. invoking) directory.
    task_ranges : list of tuple of int, optional

    TODO: do validation of task_ranges here? so models.workflow.add_submission
    always receives a definite `task_ranges`? What about if the number is
    indeterminate at submission time?

    """

    project = Project(dir_path)
    Session = init_db(project, check_exists=True)
    session = Session()

    workflow = session.query(Workflow).get(workflow_id)
    submission = workflow.add_submission(project, task_ranges)

    session.commit()

    submission_id = submission.id_
    session.close()

    return submission_id


def get_workflow_ids(dir_path=None):
    """Get the IDs of existing Workflows.

    Parameters
    ----------
    dir_path : str or Path, optional
        The directory in which the Workflows exist. By default, this is the
        working (i.e. invoking) directory.

    Returns
    -------
    workflow_ids : list of int
        List of IDs of Workflows.

    """

    project = Project(dir_path)
    Session = init_db(project, check_exists=True)
    session = Session()

    workflow_ids = [i.id_ for i in session.query(Workflow.id_)]

    session.close()

    return workflow_ids


def clean(dir_path=None):
    """Clean the directory of all content generated by `hpcflow`."""

    project = Project(dir_path)
    project.clean()


def write_runtime_files(cmd_group_sub_id, task=None, dir_path=None):
    """Write the commands files for a given command group submission.

    Parameters
    ----------
    cmd_group_sub_id : int
        ID of the command group submission for which a command file is to be
        generated.
    task : int, optional
        Task ID. What is this for???
    dir_path : str or Path, optional
        The directory in which the Workflow will be generated. By default, this
        is the working (i.e. invoking) directory.

    """
    project = Project(dir_path)
    Session = init_db(project, check_exists=True)
    session = Session()

    cg_sub = session.query(CommandGroupSubmission).get(cmd_group_sub_id)
    cg_sub.write_runtime_files(project)

    session.commit()
    session.close()


def set_task_start(cmd_group_sub_id, task_idx, dir_path=None):

    project = Project(dir_path)
    Session = init_db(project, check_exists=True)
    session = Session()

    cg_sub = session.query(CommandGroupSubmission).get(cmd_group_sub_id)
    cg_sub.set_task_start(task_idx)

    session.commit()
    session.close()


def set_task_end(cmd_group_sub_id, task_idx, dir_path=None):

    project = Project(dir_path)
    Session = init_db(project, check_exists=True)
    session = Session()

    cg_sub = session.query(CommandGroupSubmission).get(cmd_group_sub_id)
    cg_sub.set_task_end(task_idx)

    session.commit()
    session.close()


def archive(cmd_group_sub_id, task_idx, dir_path=None):
    """Initiate an archive of a given task.

    Parameters
    ----------
    cmd_group_sub_id : int
        ID of the command group submission for which an archive is to be
        started.
    task_idx : int
        The task index to be archived (or rather, the task whose working directory
        will be archived).
    dir_path : str or Path, optional
        The directory in which the Workflow will be generated. By default, this
        is the working (i.e. invoking) directory.

    """

    project = Project(dir_path)
    Session = init_db(project, check_exists=True)
    session = Session()

    cg_sub = session.query(CommandGroupSubmission).get(cmd_group_sub_id)
    cg_sub.do_archive(task_idx)

    session.commit()
    session.close()


def root_archive(workflow_id, dir_path=None):
    """Archive the root directory of the Workflow."""

    project = Project(dir_path)
    Session = init_db(project, check_exists=True)
    session = Session()

    workflow = session.query(Workflow).get(workflow_id)
    workflow.do_root_archive()

    session.commit()
    session.close()


def get_stats(dir_path=None, workflow_id=None, jsonable=True):
    'Get task statistics (as a JSON-like dict) for a project.'

    project = Project(dir_path)
    Session = init_db(project, check_exists=True)
    session = Session()

    all_workflow_ids = [i.id_ for i in session.query(Workflow.id_)]

    if not all_workflow_ids:
        msg = 'No workflows exist in directory: "{}"'
        raise ValueError(msg.format(project.dir_path))

    elif workflow_id:

        if workflow_id not in all_workflow_ids:
            msg = 'No workflow with ID "{}" was found in directory: "{}"'
            raise ValueError(msg.format(workflow_id, project.dir_path))

        workflow_ids = [workflow_id]

    else:
        workflow_ids = all_workflow_ids

    workflows = [session.query(Workflow).get(i) for i in workflow_ids]
    stats = [i.get_stats(jsonable=jsonable) for i in workflows]

    session.close()

    return stats


def get_formatted_stats(dir_path=None, workflow_id=None, max_width=100,
                        show_task_end=False):
    'Get task statistics formatted like a table.'

    stats = get_stats(dir_path, workflow_id, jsonable=True)

    out = ''
    for workflow in stats:
        out += 'Workflow ID: {}\n'.format(workflow['workflow_id'])
        for submission in workflow['submissions']:
            out += 'Submission ID: {}\n'.format(submission['submission_id'])
            for cmd_group_sub in submission['command_group_submissions']:
                out += 'Command group submission ID: {}\n'.format(
                    cmd_group_sub['command_group_submission_id'])
                out += 'Commands:\n'
                for cmd in cmd_group_sub['commands']:
                    out += '\t{}\n'.format(cmd)
                task_table = BeautifulTable(max_width=max_width)
                task_table.set_style(BeautifulTable.STYLE_BOX)
                task_table.row_separator_char = ''
                headers = [
                    '',
                    'TID',
                    'SID',
                    'Dir.',
                    'Start',
                    'Duration',
                    'Archive',
                    'memory',
                    'hostname',
                ]
                if show_task_end:
                    headers = headers[:5] + ['End'] + headers[5:]
                task_table.column_headers = headers

                for task in cmd_group_sub['tasks']:
                    row = [
                        task['order_id'],
                        task['task_id'],
                        task['scheduler_id'],
                        task['working_directory'],
                        task['start_time'] or 'pending',
                        task['duration'] or '-',
                        task['archive_status'] or '-',
                        task['memory'] or '-',
                        task['hostname'] or '-',
                    ]
                    if show_task_end:
                        row = row[:5] + [task['end_time'] or '-'] + row[5:]
                    task_table.append_row(row)

                out += str(task_table) + '\n\n'

    return out


def save_stats(save_path, dir_path=None, workflow_id=None):
    'Save task statistics as a JSON file.'

    stats = get_stats(dir_path, workflow_id, jsonable=True)

    save_path = Path(save_path)
    with save_path.open('w') as handle:
        json.dump(stats, handle, indent=4, sort_keys=True)


def kill(dir_path=None, workflow_id=None):
    'Delete jobscripts associated with a given workflow.'

    project = Project(dir_path)
    Session = init_db(project, check_exists=True)
    session = Session()

    all_workflow_ids = [i.id_ for i in session.query(Workflow.id_)]

    if not all_workflow_ids:
        msg = 'No workflows exist in directory: "{}"'
        raise ValueError(msg.format(project.dir_path))

    elif workflow_id:

        if workflow_id not in all_workflow_ids:
            msg = 'No workflow with ID "{}" was found in directory: "{}"'
            raise ValueError(msg.format(workflow_id, project.dir_path))

        workflow_ids = [workflow_id]

    else:
        workflow_ids = all_workflow_ids

    for i in workflow_ids:
        workflow = session.query(Workflow).get(i)
        workflow.kill_active()

    session.commit()
    session.close()
