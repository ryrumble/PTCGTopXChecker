import argparse

from cli import run_cli_menu
from gui import run_gui


def main() -> None:
    parser = argparse.ArgumentParser(description="PKMN Online Top X Checker")
    parser.add_argument(
        "--mode",
        choices=["cli", "gui"],
        default="cli",
        help="Run in CLI or GUI mode (default: cli)",
    )
    args = parser.parse_args()

    if args.mode == "gui":
        run_gui()
    else:
        run_cli_menu()


if __name__ == "__main__":
    main()



