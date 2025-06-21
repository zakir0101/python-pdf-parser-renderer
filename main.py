#! ./venv-12/bin/python
# PYTHON_ARGCOMPLETE_OK

import argparse
from argparse import ArgumentParser
import argcomplete
import os
from os.path import sep
import random as rand


if os.name == "nt":  # Windows
    d_drive = "D:"
else:
    d_drive = "/mnt/d"
if os.environ.get("IGCSE_PATH"):
    igcse_path = os.environ["IGCSE_PATH"]
else:
    igcse_path = f"{d_drive}{sep}Drive{sep}IGCSE-NEW"

# jwggfg

all_subjects = [
    f
    for f in os.listdir(igcse_path)
    if os.path.isdir(igcse_path + sep + f) and f.isdigit()
]


class CmdArgs:
    def load_modules(self):
        pass

    def __init__(self, args: argparse.Namespace):
        self.load_modules()
        self.mode = args.mode
        if self.mode in ["view"]:
            self.type = args.type
            self.wait_time = args.wait
            self.curr_file = None
            self.single = args.single
            self.exampaths: list[str] = args.exampath
            self.max_tj = args.max_tj
            self.open_pdf = args.summatra
            self.missing_font = args.missing_font or None
            self.range: list[int] = self.convet_range_string_to_list(
                args.range
            )
            self.f_indecies = self.convet_range_string_to_list(
                args.file_indecies
            )
            self.clean = not args.no_clean

        self.TEST_SIZE = {
            "tiny": 1,
            "small": 3,
            "meduim": 7,
            "large": 11,
            "all": None,
        }
        if self.mode in ["test"]:
            self.test = (
                args.test_type
            )  # parser , detector-count , detector-full,
            self.group = args.group
            self.data = (
                [
                    (os.path.basename(f), f) if os.path.exists(f) else f
                    for f in args.path
                ]
                if args.path
                else None
            )

            self.pause = args.pause
            self.clean = not args.no_clean
            if self.clean:
                print("setting clean")
                self.clean = int(args.clean) or 6
            self.debug = args.debug
            self.size = self.TEST_SIZE.get(args.size) or None
            self.subjects = args.subjects or all_subjects
            self.max = args.max
            self.open_pdf = args.summatra
            self.open_nvim = args.nvim
            self.force = args.force
            self.range = self.convet_range_string_to_list(args.range)
            if self.test == "subjects":
                return
            self.build_test_data()
            if not self.data:
                raise Exception("missing data for ")

        if self.mode in ["list"]:
            self.item = args.item
            self.subjects = args.subjects
            self.year = args.year
            self.exam = args.exam
            self.full = args.full
            self.row = args.row

    def convet_range_string_to_list(self, string: str):
        if string is None:
            return None
        if string == "random":
            return string
        sp = string.split(",")
        output = []
        for el in sp:
            if el.isdigit():
                output.append(int(el))
            else:
                sp2 = el.split("-")
                if len(sp2) != 2:
                    raise Exception(f"invalid range {el}")
                e1, e2 = sp2[0], sp2[1]
                if not e1.isdigit() or not e2.isdigit():
                    raise Exception(f"invalid range {el}")
                e1, e2 = int(e1), int(e2)
                for i in range(e1, e2 + 1):
                    output.append(i)

        return sorted(output)

    def set_engine(self, engine):
        self.engine = engine
        self.page_count = len(engine.pages)

    def build_test_data(
        self,
    ):
        if self.data is not None:
            return
            # self.data = [(os.path.basename(d), d) for d in self.data]
            return
        files = []
        if self.size is None:
            self.size = 12
        self.years = self.get_test_years()
        self.year_dict = {}
        for sub in self.subjects:
            if self.max and len(files) >= self.max:
                break
            spath = igcse_path + sep + sub + sep + "exams"
            sexams = [
                (f, spath + sep + f)
                for f in os.listdir(spath)
                if self.filter_exam(f, sub)
            ]
            if self.group == "random":
                rand.shuffle(sexams)
            if self.max and len(files) + len(sexams) > self.max:
                files.extend(sexams[: self.max - len(sexams)])
            else:
                files.extend(sexams)
        if self.test != "list":
            print(self.subjects)
            print("size = ", self.size)
            print("years", self.years)
            print("exams len =", len(files))
        self.data = files

    def filter_exam(self, ex_name: str, sub: str):
        if "qp" not in ex_name or not ex_name.endswith(".pdf"):
            return False
        ye = ex_name.split("_")[1][1:]
        if int(ye) not in self.years:
            return False

        if not self.year_dict.get(sub + ye):
            self.year_dict[sub + ye] = 1
            return True
        if self.year_dict[sub + ye] < self.size:
            self.year_dict[sub + ye] += 1
            return True
        return False

    def get_test_years(self):

        gr = self.group
        if gr == "all":
            year = [i for i in range(11, 24)]
        elif gr == "latest":
            year = [23]
        elif "oldest" in gr:
            last = int(gr[-1]) if gr[-1].isdigit() else 0
            year = []
            for i in range(11, 11 + 1 + last):
                year.append(i)
        elif gr.startswith("gap"):
            period = gr[-1]
            if not period.isdigit():
                raise Exception("group gap period is not defiend")
            year = [i for i in range(23, 10, -int(period))]
        elif gr == "random":
            all = [i for i in range(11, 24)]
            year = rand.sample(all, k=6)
        elif gr.startswith("year"):
            ye = gr[4:]
            year = [int(ye)]
        else:
            raise Exception("group is not correctly defined")

        return year

    @classmethod
    def add_view_subparser(cls, subparsers: argparse._SubParsersAction):
        view: argparse.ArgumentParser = subparsers.add_parser(
            "view", help="view a a page/question/pdf"
        )
        view.add_argument("type", type=str, choices=["pages", "questions"])
        view.add_argument(
            "--exampath", "--path", type=str, default=None, nargs="*"
        )
        view.add_argument("--range", type=str, default=None)
        view.add_argument("--file-indecies", "-f", type=str, default=None)
        # view.add_argument("--pages", type=str, default="1")
        view.add_argument(
            "--wait",
            type=int,
            help="time to wait before viewing the next image",
        )
        view.add_argument("--max-tj", type=int, default=10000)
        view.add_argument("--summatra", action="store_true", default=False)
        view.add_argument("--missing-font", type=int, default=0)
        view.add_argument("--single", "-r", action="store_true", default=False)
        view.add_argument(
            "--no-clean", "-nc", action="store_true", default=False
        )
        view.set_defaults(func="view_element")

    @classmethod
    def add_clear_subparser(cls, subparsers: argparse._SubParsersAction):
        clear: argparse.ArgumentParser = subparsers.add_parser(
            "clear", help="clear temp files"
        )
        clear.set_defaults(func="clear_temp_files")

    @classmethod
    def add_list_subparser(cls, subparsers: argparse._SubParsersAction):
        li: argparse.ArgumentParser = subparsers.add_parser(
            "list",
            help="list existing pdf exams / subjects / questions, and filter them",
        )
        li.add_argument(
            "item",
            type=str,
            choices=["subjects", "sub", "exams", "ex", "questions", "q"],
        )
        li.add_argument(
            "--subjects",
            "-s",
            type=str,
            nargs="*",
            choices=all_subjects,
            default=None,
        )
        li.add_argument(
            "--year",
            "-y",
            type=str,
            choices=[f"{n:02}" for n in range(1, 27)],
            default=None,
        )
        li.add_argument("--exam", "-ex", type=str, default=None)
        li.add_argument("--full", "-f", action="store_true", default=None)
        li.add_argument("--row", "-r", action="store_true", default=True)
        li.set_defaults(func="list_items")

    @classmethod
    def add_test_subparser(cls, subparsers: argparse._SubParsersAction):
        test: argparse.ArgumentParser = subparsers.add_parser(
            "test", help="run test on a set of exam pdfs"
        )
        test.add_argument(
            "test_type",
            type=str,
            choices=[
                "list",
                "font-show",
                "font-missing",
                "parser",
                "renderer-show",
                "renderer-silent",
                "questions-count",
                "questions-match",
                "pre-questions-show",
                "questions-save",
                # ___
                "extract-questions",
                "view-question",
                "view-page",
                "subjects",
                "gui",
            ],
        )

        test.add_argument("--path", type=str, default=None, nargs="*")
        years = []
        for i in range(11, 24):
            years.append(f"year{str(i)}")
        groups = [
            "latest",
            "oldest",
            "oldest2",
            "oldest4",
            "oldest6",
            "gap2",
            "gap4",
            "gap6",
            "random",
            "all",
        ] + years
        test.add_argument(
            "--group",
            type=str,
            choices=groups,
        )

        test.add_argument("--range", type=str, default=None)
        test.add_argument(
            "--size",
            type=str,
            choices=["tiny", "small", "medium", "large", "all"],
        )

        test.add_argument("--max", type=int)

        test.add_argument(
            "--no-clean", "-nc", action="store_true", default=False
        )

        test.add_argument("--clean", "-c", type=int, default=7)
        test.add_argument("--debug", "-d", action="store_true", default=False)
        test.add_argument("--pause", action="store_true", default=False)
        test.add_argument("--summatra", action="store_true", default=False)

        test.add_argument(
            "--force",
            action="store_true",
            default=False,
            help="REmake the file even if already exited !!",
        )
        test.add_argument(
            "--nvim",
            action="store_true",
            default=False,
            help="open the last 10 created files in neovim",
        )
        test.add_argument(
            "--subjects",
            "-s",
            type=str,
            nargs="*",
            choices=all_subjects,
            default=None,
        )
        test.set_defaults(func="do_tests")

    @classmethod
    def add_make_subparser(cls, subparsers: argparse._SubParsersAction):
        make: argparse.ArgumentParser = subparsers.add_parser(
            "make",
            help=(
                "make json/txt files from OCRing/embeddings the detected question\n"
                + "Note: required that the pdf is already detected\n"
                + "subcommands:\n"
                + "1. ocr : work only if the pdf is already detectd and saved\n"
                + "2. embedding: work only if the pdf is already detected and OCRed"
            ),
        )
        make.add_argument(
            "make_type",
            type=str,
            choices=["gemini-ocr", "gemini-embedding"],
        )

        make.add_argument("--path", type=str, default=None, nargs="*")
        years = []
        for i in range(11, 24):
            years.append(f"year{str(i)}")
        groups = [
            "latest",
            "oldest",
            "oldest2",
            "oldest4",
            "oldest6",
            "gap2",
            "gap4",
            "gap6",
            "random",
            "all",
        ] + years
        make.add_argument(
            "--group",
            type=str,
            choices=groups,
        )

        make.add_argument("--range", type=str, default=None)
        make.add_argument(
            "--size",
            type=str,
            choices=["tiny", "small", "medium", "large", "all"],
        )

        make.add_argument("--max", type=int)

        make.add_argument("--pause", action="store_true", default=False)
        make.add_argument(
            "--force",
            action="store_true",
            default=False,
            help="REmake the file even if already exited !!",
        )
        make.add_argument(
            "--nvim",
            action="store_true",
            default=False,
            help="open the last 10 created files in neovim",
        )
        make.add_argument(
            "--subjects",
            "-s",
            type=str,
            nargs="*",
            choices=all_subjects,
            default=None,
        )
        make.set_defaults(func="do_make")


if __name__ == "__main__":

    parser = ArgumentParser()

    parser.set_defaults(func=lambda x: print("no args provided"))
    subparsers = parser.add_subparsers(dest="mode")
    # CmdArgs.add_view_subparser(subparsers=subparsers)
    CmdArgs.add_clear_subparser(subparsers=subparsers)
    CmdArgs.add_test_subparser(subparsers=subparsers)
    CmdArgs.add_list_subparser(subparsers=subparsers)
    CmdArgs.add_make_subparser(subparsers=subparsers)
    argcomplete.autocomplete(parser, exclude=["b", "q", "ex", "sub"])

    nm = parser.parse_args()

    from cli_actions import MAIN_CALLBACK

    MAIN_CALLBACK[nm.func](CmdArgs(nm))
    # nm.func(CmdArgs(nm))
