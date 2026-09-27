import sys
from idos_updater.cli import build_arg_parser, run_cli
from idos_updater.web import run_web


def main():
    if len(sys.argv) > 1:
        parser = build_arg_parser()
        args = parser.parse_args()
        if args.web:
            run_web(args.path)
        else:
            run_cli(args)
    else:
        from idos_updater.gui import run_gui

        run_gui()


if __name__ == "__main__":
    main()
