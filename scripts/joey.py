"""Joey dev CLI: one entry point for the item-workflow commands (JY-010).

  python scripts/joey.py worktree new|remove|list ...    (scripts/joey_worktree.py)
  python scripts/joey.py close-out JY-### ...            (scripts/joey_closeout.py)

Thin dispatcher: COMMANDS maps a subcommand to its module, whose main(argv) returns the exit code. JY-011 adds
"close-out" and JY-012 adds "preview", one line each. Shared helpers live in scripts/joey_common.py.
Importing this module does no work.
"""
import argparse
import sys

import joey_closeout
import joey_common
import joey_preview
import joey_worktree

COMMANDS = {
    "worktree": joey_worktree,
    "preview": joey_preview,
    "close-out": joey_closeout,
}


def main(argv=None):
    joey_common.utf8_stdio()
    argv = list(sys.argv[1:] if argv is None else argv)
    p = argparse.ArgumentParser(prog="joey.py", description="Joey item-workflow commands.",
                                epilog="Each command has its own --help, e.g. joey.py worktree --help")
    p.add_argument("command", choices=sorted(COMMANDS))
    ns = p.parse_args(argv[:1])
    return COMMANDS[ns.command].main(argv[1:])


if __name__ == "__main__":
    sys.exit(main())
