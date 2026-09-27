import sys
from idos_updater.cli import build_arg_parser, run_cli
from idos_updater.gui import run_gui


def main():
    if len(sys.argv) > 1:
        parser = build_arg_parser()
        args = parser.parse_args()
        run_cli(args)
    else:
        run_gui()


if __name__ == "__main__":
    main()
