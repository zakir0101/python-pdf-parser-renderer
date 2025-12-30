import pprint
import random
import traceback
import json
from typing_extensions import deprecated
import tqdm
import sys
from engine.pdf_engine import PdfEngine
from engine.pdf_renderer import BaseRenderer
from engine.pdf_stream_parser import PDFStreamParser
from main import CmdArgs, all_subjects, igcse_path
import os
from os.path import sep
import gui.pdf_tester_gui as gui
from models.core_models import Subject
import engine.pdf_gui_api as api


# ******************************************************************
# ********************* CMD_MAKE **********************************
# ------------------------------------------------------------------
def do_make(args: CmdArgs):
    pass


# ******************************************************************
# ********************* CMD_LIST **********************************
# ------------------------------------------------------------------


def do_tests(args: CmdArgs):
    clear_temp_files(args)
    callbacks = {
        "list": do_list,
        # "font-show": do_test_font,
        # "font-missing": lambda x: do_test_font(x, "missing"),
        # "renderer-silent": do_test_renderer,
        # "renderer-show": do_test_renderer,
        # "parser": do_test_parser,
        # "questions-count": do_test_question,
        # "questions-match": do_test_question,
        # "pre-questions-show": do_show_question,
        # "questions-save": do_test_question,
        # -----
        "subjects": do_test_subjects_syllabus,
        "gui": do_run_gui_tester,
        "view-question": show_question,
        "view-page": show_page,
        "extract-questions": show_question,
    }
    if callbacks.get(args.test):
        callbacks[args.test](args)


def do_run_gui_tester(args: CmdArgs):
    from gui.advanced_pdf_gui import AdvancedPDFViewer

    app = AdvancedPDFViewer([f for f in args.data])
    app.mainloop()


def do_test_subjects_syllabus(args: CmdArgs):

    subjects_dict = api.load_subjects_files()
    for sub in args.subjects:
        sub_obj: Subject = subjects_dict[sub]
        print("\n\n******************************************")
        print(f"****************  {sub} *****************")
        for paper in sub_obj.papers.values():
            if args.data and str(paper.number) not in args.data:
                print(f"skipping paper {paper.number}", args.data)
                continue
            print(f"\n************+ Paper Nr {paper.number} ***************")
            print(f"************+ Paper {paper.name} ***************")
            # empty_chaps = []
            for chap in paper.chapters:
                if args.range and chap.number not in args.range:
                    print(args.range, chap.number)
                    continue
                # print(f"\n{chap.number}: {chap.name}, .... description =>")
                # print("___________________________")
                print(chap.name)
                if args.pause:
                    print(chap.description, "\n\n")
                cleaned_desc = (
                    chap.description.replace("description", "")
                    .replace("examples", "")
                    .replace("\n", "")
                    .replace("core", "")
                    .replace("extended", "")
                    .replace("*", "")
                    .replace(" ", "")
                    .replace(":", "")
                )
                # print("char_count = ", len(cleaned_desc))
                if not chap.description or len(cleaned_desc) == 0:
                    raise Exception("Found an emtpy chapter ... ")


def do_list(args: CmdArgs):
    for f in args.data:
        print(f[1], end=" ")


@deprecated("do Not use")
def do_test_font(args: CmdArgs, t_type: str = "show"):
    """this function need to be updated to test the new PdfEngine API"""

    print("TEsting fonts")
    engine: PdfEngine = PdfEngine(scaling=4, debug=True, clean=False)
    missing = set()
    for pdf in tqdm.tqdm(args.data):
        args.curr_file = pdf[1]
        args.max_tj = 4000
        engine.initialize_file(pdf[1])
        args.set_engine(engine)
        cur_range = args.range or range(1, args.page_count + 1)
        for page in cur_range:
            try:
                engine.load_page_content(page, BaseRenderer)
                for font in engine.font_map.values():
                    if t_type == "show":
                        font.debug_font()
                    elif t_type == "missing":
                        if not font.is_type3 and font.use_toy_font:
                            missing.add(font.base_font)
            except Exception as e:
                print(e)
                print(f"{pdf[1]}:{page}")
                raise

    if t_type == "missing":
        print("missing fonts :>")
        print(missing)
        pass


@deprecated("do Not use")
def do_test_parser(args: CmdArgs):
    """this function need to be updated to test the new PdfEngine API"""

    print("************* Testing Parser ****************\n\n")
    engine: PdfEngine = PdfEngine(scaling=4, debug=True, clean=False)
    # errors_dict = {}
    exception_stats = {}  # defaultdict(lambda: (0, "empty", []))
    total_pages = 0
    total_passed = 0
    stop = False
    all_locations = []
    for pdf in tqdm.tqdm(args.data):
        if stop:
            break
        args.curr_file = pdf[1]
        args.max_tj = 4000
        engine.initialize_file(pdf[1])
        args.set_engine(engine)
        for page in range(1, args.page_count + 1):
            total_pages += 1
            try:
                engine.load_page_content(page, BaseRenderer)
                engine.debug_original_stream()
                parser = PDFStreamParser().parse_stream(engine.current_stream)
                for cmd in parser.iterate():
                    pass
                total_passed += 1
            except Exception as e:
                exception_key = get_exception_key(e)
                location = f"{pdf[1]}:{page}"
                print(f"Error: {location}")
                all_locations.append(location)
                if exception_key not in exception_stats:
                    full_traceback = traceback.format_exc()
                    exception_stats[exception_key] = {
                        "count": 1,
                        "msg": full_traceback,
                        "location": [location],
                    }
                else:
                    exception_stats[exception_key]["count"] += 1
                    exception_stats[exception_key]["location"].append(location)

                if args.pause:
                    stop = True
                    break
    print("\n**********************************")
    print("Total number of Pages = ", total_pages)
    print("Passt percent", round(total_passed / total_pages * 100), "%")

    for key, value in exception_stats.items():
        print("\n**********************************\n")
        print(key)
        print("count = ", value["count"])
        print("percent = ", round(value["count"] / total_pages * 100), "%")
        print(value["msg"])
        print(value["location"])
        print("\n\n\n")

    pprint.pprint(all_locations)
    with open(f"output{sep}fix_list.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(all_locations))


@deprecated("do Not use")
def do_test_renderer(args: CmdArgs):
    """this function need to be updated to test the new PdfEngine API"""

    engine: PdfEngine = PdfEngine(scaling=4, debug=True, clean=False)
    exception_stats = {}  # defaultdict(lambda: (0, "empty", []))
    total_pages = 0
    total_passed = 0
    stop = False
    is_show = args.test == "renderer-show"
    # ----
    if is_show:
        gui.start(-1000, -1)
    wrong_rendered = []
    for pdf in tqdm.tqdm(args.data):
        if stop:
            break
        args.curr_file = pdf[1]
        args.max_tj = 4000
        engine.initialize_file(pdf[1])
        args.set_engine(engine)
        engine.clean = False
        pages_range = [i for i in range(1, args.page_count + 1)]
        if args.range:
            if args.range == "random":
                pages_range = random.sample(pages_range, k=args.size)
            elif isinstance(args.range, list):
                pages_range = [i for i in args.range if i in pages_range]
            else:
                raise Exception("unsupported range", args.range)
        for page in pages_range:
            total_pages += 1
            try:
                engine.load_page_content(page, BaseRenderer)
                engine.debug_original_stream()
                engine.execute_page_stream(max_show=args.max_tj, mode=0)
                if is_show:
                    surf = engine.renderer.surface
                    raitio = (
                        engine.scaled_page_width / engine.scaled_page_height
                    )
                    res = gui.show_page(surf, raitio)
                    print("status", res)
                    if res == gui.STATE_WRONG:
                        location = f"{pdf[1]}:{page}"
                        print("added to list")
                        wrong_rendered.append(location)
                    elif res == gui.STATE_CORRECT:
                        total_passed += 1
                    else:
                        stop = True
                        break

                else:

                    total_passed += 1

            except Exception as e:
                location = f"{pdf[1]}:{page}"
                print(f"Error: {location}")

                if not is_show:
                    exception_key = get_exception_key(e)
                    if exception_key not in exception_stats:
                        full_traceback = traceback.format_exc()
                        exception_stats[exception_key] = {
                            "count": 1,
                            "msg": full_traceback,
                            "location": [location],
                        }
                    else:
                        exception_stats[exception_key]["count"] += 1
                        # exception_stats[exception_key]["files"].append(
                        # os.path.basename(pdf[0])
                        # )
                if args.pause:
                    raise Exception(e)
                    stop = True
                    break

    print("\n**********************************")
    print("Total number of Pages = ", total_pages)
    print("Passt percent", round(total_passed / total_pages * 100), "%")
    if is_show:
        for i, f in enumerate(wrong_rendered):
            print(f"{i}. {f}")
        pass
    else:

        for key, value in exception_stats.items():
            print("\n**********************************\n")
            print(key)
            print("count = ", value["count"])
            print("percent = ", round(value["count"] / total_pages * 100), "%")
            print(value["msg"])
            print(value["location"])
            print("\n\n\n")
        # pprint.pprint(exception_stats)


def get_exception_key(e: Exception):

    exc_type = type(e).__name__
    exc_msg = str(e)
    _, _, exc_traceback = sys.exc_info()
    if exc_traceback:
        tb_frames = traceback.extract_tb(exc_traceback)
        # Get the origin frame (where the exception was raised)
        origin_frame = tb_frames[0]
        filename = origin_frame.filename
        line_no = origin_frame.lineno
    else:
        filename, line_no = "unknown", 0

    exception_key = (exc_type, exc_msg, filename, line_no)
    return exception_key

    # in exams loop
    # in page loop


@deprecated("do Not use")
def do_show_question(args: CmdArgs):
    pass


@deprecated("do Not use")
def do_test_question(
    args: CmdArgs,
):
    pass


# ******************************************************************
# ********************* CMD_LIST **********************************
# ------------------------------------------------------------------


def list_items(args: CmdArgs):
    search_item = args.item
    callbacks = [
        ("subjects", list_subjects),
        ("exams", list_exams),
        ("questions", list_questions),
    ]
    for name, cback in callbacks:
        if name.startswith(search_item):
            cback(args)


def list_questions(args: CmdArgs):

    pass


def list_exams(args: CmdArgs):
    subs = args.subjects or all_subjects
    exams = []

    def filter_exam(ex_name: str):
        if "qp" not in ex_name or not ex_name.endswith(".pdf"):
            return False
        if not args.year or not args.year.isdigit:
            return True
        return ex_name.split("_")[1][1:] == args.year

    for s in subs:
        if s not in all_subjects:
            continue
        spath = f"{igcse_path}{sep}{s}{sep}exams"
        sexams = [
            (f, spath + sep + f) for f in os.listdir(spath) if filter_exam(f)
        ]
        exams.extend(sexams)
    seperator = " " if args.row else "\n"
    for ex in exams:
        full = args.full or False
        print(ex[int(full)], end=seperator)


def list_subjects(args: CmdArgs):
    for sub in all_subjects:
        print(sub)


# ******************************************************************
# ********************* CMD_VIEW **********************************
# ------------------------------------------------------------------


def show_question(args: CmdArgs):
    debugging = args.debug and PdfEngine.M_DEBUG
    is_extract = args.test == "extract-questions"
    clean = args.clean
    total_error = 0
    SCALING = 4
    engine: PdfEngine = PdfEngine(SCALING, clean)
    # print(args.data, type(args.data))
    engine.set_files(args.data)
    if not is_extract:
        gui.start(-1, -1)
    for pdf_index in tqdm.tqdm(range(engine.all_pdf_count)):
        is_ok = engine.proccess_next_pdf_file()
        # print("\n")
        # print("***************  exam  ******************")
        # print(f"{engine.pdf_path}")

        sub_id = engine.pdf_name.split("_")[0]
        exam_id = engine.pdf_name.split(".")[0]
        out_path = (
            f"{igcse_path}{sep}{sub_id}{sep}pdf-extraction{sep}{exam_id}"
        )
        if is_extract and os.path.exists(f"{out_path}{sep}v1.json"):
            # print("Skipping File .. already proccessed")
            pass
            # continue

        if not is_ok:
            break
        try:
            engine.extract_questions_from_pdf(debugging, clean)
        except Exception as e:
            print(traceback.format_exc())
            print("Error > SKipping file :", e)
            total_error += 1
            continue
        if is_extract:
            out = [
                q.__to_dict__() for q in engine.question_detector.question_list
            ]
            out_path = (
                f"{igcse_path}{sep}{sub_id}{sep}pdf-extraction{sep}{exam_id}"
            )
            os.makedirs(out_path, exist_ok=True)
            with open(f"{out_path}{sep}v1.json", "w", encoding="utf-8") as f:
                out_dict = {
                    "scale": SCALING,
                    "page_width": engine.pages[1].mediabox.width,
                    "page_height": engine.pages[1].mediabox.height,
                    "line_height": engine.line_height,
                    "questions": out,
                }
                # pprint.pprint(out_dict)
                f.write(json.dumps(out_dict, ensure_ascii=False, indent=4))
            # print(f"saved successfully in {out_path}")
            # engine.question_detector.print_final_results(engine.pdf_path)
        else:
            for nr in args.range:
                q_surf = engine.render_a_question(nr)
                gui.show_page(q_surf, True)

    print("\n\n\ntotal error files = ", total_error)


def show_page(args: CmdArgs):
    debugging = args.debug and PdfEngine.M_DEBUG
    clean = args.clean  # args.clean and(  PdfEngine.O_CLEAN_HEADER_FOOTER )
    engine: PdfEngine = PdfEngine(4, debugging, clean)
    engine.set_files(args.data)
    gui.start(-1, -1)
    wrong_list = []
    is_done = False
    for pdf_index in range(engine.all_pdf_count):
        if is_done:
            break
        is_ok = engine.proccess_next_pdf_file()
        print("\n")
        print("***************  exam  ******************")
        print(f"{engine.pdf_path}")
        if not is_ok:
            print("Exiting ..")
            break
        page_range = args.range or range(1, len(engine.pages) + 1)
        for page in page_range:
            surf = engine.render_pdf_page(page)
            stat = gui.show_page(surf, True)
            if stat == gui.STATE_WRONG:
                wrong_list.append(engine.pdf_path + ":" + str(page))
            elif stat == gui.STATE_DONE:
                is_done = True
                break

    print("wrong rendered pages")
    print(" ".join(wrong_list))


# ******************************************************************
# ********************* CMD_CLEAR **********************************
# ------------------------------------------------------------------


def clear_temp_files(args: CmdArgs):

    for f in os.listdir("temp"):
        if os.path.isdir(f"temp{sep}{f}"):
            continue
        # print(f"removing {f}")
        os.remove(f"temp{sep}{f}")

    for f in os.listdir("output"):
        if f.startswith("glyphs_"):
            # print(f"removing {f}")
            os.remove(f"output{sep}{f}")
        if f.endswith("png"):
            # print(f"removing {f}")
            os.remove(f"output{sep}{f}")


MAIN_CALLBACK = {
    "do_tests": do_tests,
    "list_items": list_items,
    "clear_temp_files": clear_temp_files,
}
