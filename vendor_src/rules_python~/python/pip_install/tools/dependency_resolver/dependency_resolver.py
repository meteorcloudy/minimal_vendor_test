# Copyright 2023 The Bazel Authors. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"Set defaults for the pip-compile command to run it under Bazel"

import atexit
import os
import shutil
import sys
from pathlib import Path

import piptools.writer as piptools_writer
from piptools.scripts.compile import cli

from python.runfiles import runfiles

# Replace the os.replace function with shutil.copy to work around os.replace not being able to
# replace or move files across filesystems.
os.replace = shutil.copy

# Next, we override the annotation_style_split and annotation_style_line functions to replace the
# backslashes in the paths with forward slashes. This is so that we can have the same requirements
# file on Windows and Unix-like.
original_annotation_style_split = piptools_writer.annotation_style_split
original_annotation_style_line = piptools_writer.annotation_style_line


def annotation_style_split(required_by) -> str:
    required_by = set([v.replace("\\", "/") for v in required_by])
    return original_annotation_style_split(required_by)


def annotation_style_line(required_by) -> str:
    required_by = set([v.replace("\\", "/") for v in required_by])
    return original_annotation_style_line(required_by)


piptools_writer.annotation_style_split = annotation_style_split
piptools_writer.annotation_style_line = annotation_style_line


def _select_golden_requirements_file(
    requirements_txt, requirements_linux, requirements_darwin, requirements_windows
):
    """Switch the golden requirements file, used to validate if updates are needed,
    to a specified platform specific one.  Fallback on the platform independent one.
    """

    plat = sys.platform
    if plat == "linux" and requirements_linux is not None:
        return requirements_linux
    elif plat == "darwin" and requirements_darwin is not None:
        return requirements_darwin
    elif plat == "win32" and requirements_windows is not None:
        return requirements_windows
    else:
        return requirements_txt


def _locate(bazel_runfiles, file):
    """Look up the file via Rlocation"""

    if not file:
        return file

    return bazel_runfiles.Rlocation(file)


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(
            "Expected at least two arguments: requirements_in requirements_out",
            file=sys.stderr,
        )
        sys.exit(1)

    parse_str_none = lambda s: None if s == "None" else s
    bazel_runfiles = runfiles.Create()

    requirements_in = sys.argv.pop(1)
    requirements_txt = sys.argv.pop(1)
    requirements_linux = parse_str_none(sys.argv.pop(1))
    requirements_darwin = parse_str_none(sys.argv.pop(1))
    requirements_windows = parse_str_none(sys.argv.pop(1))
    update_target_label = sys.argv.pop(1)

    resolved_requirements_in = _locate(bazel_runfiles, requirements_in)
    resolved_requirements_txt = _locate(bazel_runfiles, requirements_txt)

    # Files in the runfiles directory has the following naming schema:
    # Main repo: __main__/<path_to_file>
    # External repo: <workspace name>/<path_to_file>
    # We want to strip both __main__ and <workspace name> from the absolute prefix
    # to keep the requirements lock file agnostic.
    repository_prefix = requirements_txt[: requirements_txt.index("/") + 1]
    absolute_path_prefix = resolved_requirements_txt[
        : -(len(requirements_txt) - len(repository_prefix))
    ]

    # As requirements_in might contain references to generated files we want to
    # use the runfiles file first. Thus, we need to compute the relative path
    # from the execution root.
    # Note: Windows cannot reference generated files without runfiles support enabled.
    requirements_in_relative = requirements_in[len(repository_prefix) :]
    requirements_txt_relative = requirements_txt[len(repository_prefix) :]

    # Before loading click, set the locale for its parser.
    # If it leaks through to the system setting, it may fail:
    # RuntimeError: Click will abort further execution because Python 3 was configured to use ASCII
    # as encoding for the environment. Consult https://click.palletsprojects.com/python3/ for
    # mitigation steps.
    os.environ["LC_ALL"] = "C.UTF-8"
    os.environ["LANG"] = "C.UTF-8"

    UPDATE = True
    # Detect if we are running under `bazel test`.
    if "TEST_TMPDIR" in os.environ:
        UPDATE = False
        # pip-compile wants the cache files to be writeable, but if we point
        # to the real user cache, Bazel sandboxing makes the file read-only
        # and we fail.
        # In theory this makes the test more hermetic as well.
        sys.argv.append("--cache-dir")
        sys.argv.append(os.environ["TEST_TMPDIR"])
        # Make a copy for pip-compile to read and mutate.
        requirements_out = os.path.join(
            os.environ["TEST_TMPDIR"], os.path.basename(requirements_txt) + ".out"
        )
        # Those two files won't necessarily be on the same filesystem, so we can't use os.replace
        # or shutil.copyfile, as they will fail with OSError: [Errno 18] Invalid cross-device link.
        shutil.copy(resolved_requirements_txt, requirements_out)

    update_command = os.getenv("CUSTOM_COMPILE_COMMAND") or "bazel run %s" % (
        update_target_label,
    )

    os.environ["CUSTOM_COMPILE_COMMAND"] = update_command
    os.environ["PIP_CONFIG_FILE"] = os.getenv("PIP_CONFIG_FILE") or os.devnull

    sys.argv.append("--generate-hashes")
    sys.argv.append("--output-file")
    sys.argv.append(requirements_txt_relative if UPDATE else requirements_out)
    sys.argv.append(
        requirements_in_relative
        if Path(requirements_in_relative).exists()
        else resolved_requirements_in
    )
    print(sys.argv)

    if UPDATE:
        print("Updating " + requirements_txt_relative)
        if "BUILD_WORKSPACE_DIRECTORY" in os.environ:
            workspace = os.environ["BUILD_WORKSPACE_DIRECTORY"]
            requirements_txt_tree = os.path.join(workspace, requirements_txt_relative)
            # In most cases, requirements_txt will be a symlink to the real file in the source tree.
            # If symlinks are not enabled (e.g. on Windows), then requirements_txt will be a copy,
            # and we should copy the updated requirements back to the source tree.
            if not os.path.samefile(resolved_requirements_txt, requirements_txt_tree):
                atexit.register(
                    lambda: shutil.copy(
                        resolved_requirements_txt, requirements_txt_tree
                    )
                )
        cli()
        requirements_txt_relative_path = Path(requirements_txt_relative)
        content = requirements_txt_relative_path.read_text()
        content = content.replace(absolute_path_prefix, "")
        requirements_txt_relative_path.write_text(content)
    else:
        # cli will exit(0) on success
        try:
            print("Checking " + requirements_txt)
            cli()
            print("cli() should exit", file=sys.stderr)
            sys.exit(1)
        except SystemExit as e:
            if e.code == 2:
                print(
                    "pip-compile exited with code 2. This means that pip-compile found "
                    "incompatible requirements or could not find a version that matches "
                    f"the install requirement in {requirements_in_relative}.",
                    file=sys.stderr,
                )
                sys.exit(1)
            elif e.code == 0:
                golden_filename = _select_golden_requirements_file(
                    requirements_txt,
                    requirements_linux,
                    requirements_darwin,
                    requirements_windows,
                )
                golden = open(_locate(bazel_runfiles, golden_filename)).readlines()
                out = open(requirements_out).readlines()
                out = [line.replace(absolute_path_prefix, "") for line in out]
                if golden != out:
                    import difflib

                    print("".join(difflib.unified_diff(golden, out)), file=sys.stderr)
                    print(
                        "Lock file out of date. Run '"
                        + update_command
                        + "' to update.",
                        file=sys.stderr,
                    )
                    sys.exit(1)
                sys.exit(0)
            else:
                print(
                    f"pip-compile unexpectedly exited with code {e.code}.",
                    file=sys.stderr,
                )
                sys.exit(1)
