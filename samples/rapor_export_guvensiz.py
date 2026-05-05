"""CSV/rapor export odevi - guvensiz teslim."""

import os


def export_report(path: str, text: str) -> None:
    os.system("echo " + text + " > " + path)


if __name__ == "__main__":
    export_report("report.csv", "danger")
