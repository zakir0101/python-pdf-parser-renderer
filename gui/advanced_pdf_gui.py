#! ./venv/bin/python

import json
import io
import asyncio
import zipfile
import tkinter as tk

from playwright.async_api import async_playwright
from tkinter import ttk
import os
from pathlib import Path
from os.path import sep
import requests
from PIL import Image, ImageTk
import cairo  # For type hinting and direct use if necessary

# MinerU

# from tkinter import filedialog  # Though not used for file picking yet
# from functools import partial  # For cleaner command binding if needed
import traceback
import importlib
from engine.pdf_utils import open_pdf_using_sumatra
from detectors.ocr_detectors import OcrQuestion, OcrItem


# Import for reloading and instantiation
from engine import pdf_engine as pdf_engine_module
from engine import (
    pdf_renderer as pdf_renderer_module,
)  # Assuming these are modules
from engine import pdf_font as pdf_font_module
from detectors import question_detectors as q_detectors_module
from models import question as q_model_module
from models import core_models as core_model_module

# from detectors.question_detectors import QuestionDetector as q_detectors_module
# from detectors.question_detectors import ( QuestionDetectorBase as qbase_detectors_module,)
from engine import engine_state as pdf_state_module

from engine.pdf_engine import PdfEngine

from external.markdown import render_markdown_to_png

ALL_MODULES = [
    core_model_module,
    pdf_font_module,
    q_model_module,
    pdf_state_module,
    # qbase_detectors_module,
    pdf_renderer_module,
    q_detectors_module,
    pdf_engine_module,
]

KEY_SEQUENCE_TIMEOUT = 2000
KAGGLE_SERVER_URL = "https://10e6-34-30-79-56.ngrok-free.app"
KAGGLE_SERVER_URL += "/predict"
"""
Advanced PDF Viewer GUI application.

This module implements a Tkinter-based GUI for viewing and interacting with PDF files.
It supports navigation by page and by extracted questions, debugging rendering of pages
and question extraction, and live reloading of its PDF processing engine.
The GUI displays PDF pages or question representations as images on a canvas.
"""


class AdvancedPDFViewer(tk.Tk):
    """
    Main application class for the Advanced PDF Viewer.

    Manages the main window, UI frames (controls, display, status bar),
    event handling (button clicks, keyboard shortcuts), and interaction
    with the PdfEngine for PDF processing and rendering.
    """

    def __init__(self, pdf_pathes):
        """
        Initializes the AdvancedPDFViewer application.

        Sets up the main window, PDF engine instance, UI frames, widgets,
        and keyboard shortcuts. Also loads the initial PDF if available.
        """
        super().__init__()
        self.example_counter = 3
        self._photo_image_ref = (
            None  # Keep reference to PhotoImage preventing garbage collection
        )

        self.title("Advanced PDF Viewer")
        self.geometry("1024x768")

        # Initialize PDF Engine
        self.engine = PdfEngine(
            scaling=4
        )  # Initial instantiation using PdfEngine directly
        self.navigation_mode = "page"  # "page" or "question"
        self.current_page_number = 0
        self.total_pages = 0
        self.current_question_number = 0
        self.current_surface: cairo.ImageSurface | None = None
        self.total_questions = 0
        self.questions_list = []  # To store extracted questions
        # TODO: Make PDF loading more dynamic, e.g., via a file dialog or config
        sample_pdf_paths = [
            "PDFs/9702_m23_qp_12.pdf",
            "PDFs/9702_m23_qp_22.pdf",
        ]
        sample_pdf_paths = pdf_pathes
        # my Vars
        self.img_copy_2 = None
        self.img_copy = None
        self.rel_scale = 1
        self.rel_scale_2 = 1
        self.layout_detection = 0
        self.ocr_mode = ""
        self.dual_display_mode = 1
        # Ensure the PDFs directory exists for sample paths if running from repo root
        # For now, assuming these paths are valid relative to where the script is run
        # Or that the PdfEngine handles path resolution.
        self.engine.set_files(sample_pdf_paths)

        # Create main frames
        self.display_frame = ttk.Frame(self, relief=tk.GROOVE, borderwidth=2)
        self.controls_frame = ttk.Frame(self, relief=tk.GROOVE, borderwidth=2)
        self.status_bar_frame = ttk.Frame(
            self, relief=tk.GROOVE, borderwidth=2
        )

        # Layout the frames

        self.controls_frame.pack(side=tk.LEFT, fill=tk.Y, padx=5, pady=5)
        self.status_bar_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=5, pady=5)
        self.display_frame.pack(
            side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5, pady=5
        )

        # Display Frame setup for image rendering with scrollbars
        self.v_scrollbar = ttk.Scrollbar(
            self.display_frame, orient=tk.VERTICAL
        )
        self.h_scrollbar = ttk.Scrollbar(
            self.display_frame, orient=tk.HORIZONTAL
        )

        self.display_canvas = tk.Canvas(
            self.display_frame,
            bg="lightgray",  # Changed bg for visibility
            yscrollcommand=self.v_scrollbar.set,
            xscrollcommand=self.h_scrollbar.set,
        )

        self.v_scrollbar.config(command=self.display_canvas.yview)
        self.h_scrollbar.config(command=self.display_canvas.xview)

        self.v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.h_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)
        # Important: Pack canvas AFTER scrollbars if scrollbars are outside,
        # or ensure canvas is the primary widget if scrollbars are inside its allocated space.
        # Current packing order (display_frame packs canvas and scrollbars) is fine.
        self.display_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Create an image item on the canvas. This item will be updated with new page/question images.
        self.canvas_image_item = self.display_canvas.create_image(
            0, 0, anchor=tk.NW, image=None
        )

        self.canvas_image_item_2 = self.display_canvas.create_image(
            0, 0, anchor=tk.NW, image=None
        )
        # --- Controls Frame ---
        # PDF Navigation Buttons
        self.prev_pdf_button = ttk.Button(
            self.controls_frame,
            text="Previous PDF (Ctrl-Alt-H)",
            command=self.previous_pdf_file,
        )
        self.prev_pdf_button.pack(fill=tk.X, padx=5, pady=2)

        self.next_pdf_button = ttk.Button(
            self.controls_frame,
            text="Next PDF (Ctrl-Alt-L)",
            command=self.next_pdf_file,
        )
        self.next_pdf_button.pack(fill=tk.X, padx=5, pady=2)

        ttk.Separator(self.controls_frame, orient=tk.HORIZONTAL).pack(
            fill=tk.X, pady=10
        )

        # Page/Item Navigation Buttons
        self.prev_item_button = ttk.Button(
            self.controls_frame,
            text="Previous Item (Ctrl-Alt-K)",
            command=self.previous_item,
        )
        self.prev_item_button.pack(fill=tk.X, padx=5, pady=2)

        self.next_item_button = ttk.Button(
            self.controls_frame,
            text="Next Item (Ctrl-Alt-J)",
            command=self.next_item,
        )
        self.next_item_button.pack(fill=tk.X, padx=5, pady=2)

        ttk.Separator(self.controls_frame, orient=tk.HORIZONTAL).pack(
            fill=tk.X, pady=10
        )

        # Mode Switching Buttons
        self.page_mode_button = ttk.Button(
            self.controls_frame,
            text="View Pages (Ctrl+P)",
            command=self.switch_to_page_mode,
        )
        self.page_mode_button.pack(fill=tk.X, padx=5, pady=2)

        self.question_mode_button = ttk.Button(
            self.controls_frame,
            text="View Questions (Ctrl+Q)",
            command=self.switch_to_question_mode,
        )
        self.question_mode_button.pack(fill=tk.X, padx=5, pady=2)

        ttk.Separator(self.controls_frame, orient=tk.HORIZONTAL).pack(
            fill=tk.X, pady=10
        )

        # Debugging Button
        self.debug_button = ttk.Button(
            self.controls_frame,
            text="Debug Item (Ctrl+D)",
            command=self.debug_current_item,
        )
        self.debug_button.pack(fill=tk.X, padx=5, pady=2)

        # Combined Debug (Ctrl+Shift+D) - conceptual, button might be redundant if shortcut is primary
        # For now, let's rely on the shortcut for combined_debug=True.
        # If a button is desired, it could be added here.

        ttk.Separator(self.controls_frame, orient=tk.HORIZONTAL).pack(
            fill=tk.X, pady=10
        )

        # Reloading Button
        self.reload_button = ttk.Button(
            self.controls_frame,
            text="Reload Engine (Ctrl+R)",
            command=self.reload_engine_code,
        )
        self.reload_button.pack(fill=tk.X, padx=5, pady=2)

        empty_frame = ttk.Frame(
            self.controls_frame, relief=tk.GROOVE, borderwidth=2
        )
        empty_frame.pack(fill=tk.X, padx=5, pady=5, expand=True)

        self.md_button = ttk.Button(
            self.controls_frame,
            text="OCR.md (Ctrl+m)",
            command=lambda x: self.toggle_ocr_md(1),
        )
        self.md_button.pack(fill=tk.X, padx=5, pady=2)

        self.tex_button = ttk.Button(
            self.controls_frame,
            text="OCR.latex (Ctrl+l)",
            command=self.toggle_ocr_tex,
        )
        self.tex_button.pack(fill=tk.X, padx=5, pady=2)

        self.png_button = ttk.Button(
            self.controls_frame,
            text="Save PNG (Ctrl+s)",
            command=self.save_surface_to_png,
        )
        self.png_button.pack(fill=tk.X, padx=5, pady=2)

        self.summatra_button = ttk.Button(
            self.controls_frame,
            text="Open Summatra (Ctrl+S)",
            command=lambda x: open_pdf_using_sumatra(
                self.engine.current_pdf_document
            ),
        )
        self.summatra_button.pack(fill=tk.X, padx=5, pady=(2, 20))

        # --- Status Bar Frame ---
        self.status_bar_text = tk.StringVar()
        self.status_bar_label = ttk.Label(
            self.status_bar_frame,
            textvariable=self.status_bar_text,
            relief=tk.SUNKEN,
            anchor=tk.W,
            wraplength=800,
            justify=tk.LEFT,
        )  # wraplength and justify for long messages
        self.status_bar_label.pack(fill=tk.X, expand=True, padx=2, pady=2)
        # Initial message set by update_status_bar in __init__ later

        # --- Keyboard Shortcuts ---
        self.bind("<Control-Alt-l>", lambda event: self.next_pdf_file())
        self.bind("<Control-Alt-h>", lambda event: self.previous_pdf_file())
        self.bind("<Control-Alt-j>", lambda event: self.next_item())
        self.bind("<Control-Alt-k>", lambda event: self.previous_item())
        self.bind("<Control-p>", self.switch_to_page_mode)
        self.bind("<Control-q>", self.switch_to_question_mode)
        self.bind(
            "<Control-d>",
            lambda event: self.debug_current_item(combined_debug=False),
        )
        self.bind(
            "<Control-Shift-D>",
            lambda event: self.debug_current_item(combined_debug=True),
        )
        self.bind("<Control-r>", self.reload_engine_code)
        self.bind(
            "<Control-Shift-S>",
            lambda x: open_pdf_using_sumatra(self.engine.current_pdf_document),
        )

        self.bind("<Control-s>", self.save_surface_to_png)
        self.bind("<Control-m>", lambda x: self.toggle_ocr_md(1))
        self.bind("<Control-Shift-M>", lambda x: self.toggle_ocr_md(2))
        self.bind("<Control-l>", self.toggle_ocr_tex)

        # scrolling :

        self.bind(
            "<j>", lambda x: self.display_canvas.yview_scroll(1, "units")
        )
        self.bind(
            "<k>", lambda x: self.display_canvas.yview_scroll(-1, "units")
        )
        self.bind("<Control-t>", lambda x: self.toggle_layout_detection(5))
        self.bind(
            "<Control-Shift-T>", lambda x: self.toggle_layout_detection(2)
        )
        self.bind("<Control-Alt-t>", lambda x: self.toggle_layout_detection(3))
        self.bind(
            "<Control-Alt-Shift-T>", lambda x: self.toggle_layout_detection(4)
        )

        self.bind("<Control-w>", self.enter_sequence_mode)
        # --- Initial Load ---
        self.update_status_bar(
            "Welcome! Load a PDF to begin."
        )  # Initial status
        self.update_all_button_states()  # Initial button state
        if self.engine.all_pdf_paths:
            self.next_pdf_file()  # Load the first PDF

        # You can also use <Control-W> (capital W), Tkinter is often case-insensitive
        # for the letter part, but <Control-w> is conventional.

    def enter_sequence_mode(self, event=None):
        """
        Called when Ctrl+W is pressed. Puts the app in "waiting" mode.
        """
        print("Ctrl+W pressed. Waiting for next key...")
        self.ctrl_w_pressed = True
        # self.update_status_bar("Ctrl+W ... (press 1, 2, or 3)")

        # --- Step 2: Temporarily bind the command keys ---
        self.bind("1", lambda e: self.handle_command_key(1))
        self.bind("2", lambda e: self.handle_command_key(2))
        self.bind("3", lambda e: self.handle_command_key(3))
        self.bind("q", lambda e: self.handle_command_key("q"))

        self.bind("<Key>", self.reset_sequence_mode)

        self.timer_id = self.after(
            KEY_SEQUENCE_TIMEOUT, self.reset_sequence_mode
        )

        # The 'return "break"' is important. It prevents Tkinter from
        # propagating the event further (e.g., a default OS action for Ctrl+W).
        return "break"

    def handle_command_key(self, number):
        """
        This is a wrapper that calls the target function and then resets the state.
        """
        # Only do something if we are in the correct state.
        if self.ctrl_w_pressed:
            if number == "q":
                self.destroy()
                exit(0)
            elif number in [1, 2, 3]:
                self.change_dual_mode(number)

            self.reset_sequence_mode(success=True)

        return "break"

    def reset_sequence_mode(self, event=None, success=False):
        """
        Resets the application to the normal state.
        """
        # We need to make sure this function body only runs once per sequence.
        if not self.ctrl_w_pressed:
            return

        # Cancel the pending timer if it exists
        if self.timer_id:
            self.after_cancel(self.timer_id)
            self.timer_id = None

        # Unbind the temporary keys
        self.unbind("1")
        self.unbind("2")
        self.unbind("3")
        self.unbind("q")
        self.unbind("<Key>")  # Unbind the fallback too

        self.ctrl_w_pressed = False

        if not success:
            message = "Sequence cancelled (timeout or invalid key)."
            print(message)
            # self.info_label.config(text=message, fg="red")

        # A small delay before resetting the label text to "Ready"
        # self.update_status_bar("Ready. Press Ctrl+W, then 1, 2, or 3.")

    def toggle_layout_detection(self, mode: int):
        if self.layout_detection > 0:
            self.layout_detection = 0
        else:
            self.layout_detection = mode
        self.render_current_page_or_question()
        msg = f"Turned {'On' if self.layout_detection else 'Off'} Layout Detection [{'YOLO' if mode == 1 else 'Miner-U'}]"
        self.update_status_bar(msg)
        print(msg)

    def save_surface_to_png(self, event=None):

        if self.current_surface:
            img_path = sep.join([".", "output", "gui_saved_image.png"])
            self.current_surface.write_to_png(img_path)
            self.update_status_bar("image saved Successfully")
            print("image saved Successfully")
            return img_path
        return False

    def image_to_png_bytes(self, cairo_image_surface: cairo.ImageSurface):
        surface_format = cairo_image_surface.get_format()
        width = cairo_image_surface.get_width()
        height = cairo_image_surface.get_height()
        stride = cairo_image_surface.get_stride()

        cairo_image_surface.flush()

        image_data_buffer = cairo_image_surface.get_data()

        pil_image = None
        if surface_format != cairo.FORMAT_ARGB32:
            raise Exception("make sure to use ARGB32")
        pil_image = Image.frombytes(
            "RGBA",
            (width, height),
            image_data_buffer.tobytes(),
            "raw",
            "BGRA",
            stride,
        )
        bytes_png = io.BytesIO()
        pil_image.save(bytes_png, format="png")
        return bytes_png.getvalue()

    def update_status_bar(self, general_message: str = ""):
        """
        Updates the status bar with current file, mode, item, and a general message.

        Args:
            general_message (str, optional): A specific message to display.
                                            Defaults to "".
        """
        file_info = "File: None"
        if (
            self.engine
            and hasattr(self.engine, "pdf_path")
            and self.engine.pdf_path
        ):  # Check pdf_path exists
            index = f"{self.engine.current_pdf_index + 1}/{self.engine.all_pdf_count}"
            file_info = (
                f"File: {os.path.basename(self.engine.pdf_path)} {index}"
            )

        mode_info = f"Mode: {self.navigation_mode.capitalize()}"
        item_info = ""

        if self.navigation_mode == "page":
            if (
                self.engine.current_pdf_document and self.total_pages > 0
            ):  # Check if PDF is loaded for page info
                item_info = (
                    f"Page: {self.current_page_number}/{self.total_pages}"
                )
            else:
                item_info = "Page: N/A"
        elif self.navigation_mode == "question":
            if (
                self.engine.current_pdf_document and self.total_questions > 0
            ):  # Check if PDF is loaded for q info
                item_info = f"Question: {self.current_question_number}/{self.total_questions}"
            else:
                item_info = "Question: N/A"

        status_parts = [file_info, mode_info, item_info]
        if general_message:
            # Limit general message length if too long, or let wraplength handle it
            status_parts.append(f"Status: {general_message}")

        full_status = " | ".join(
            filter(None, status_parts)
        )  # filter(None,...) to remove empty strings if item_info is empty
        self.status_bar_text.set(full_status)
        # print(f"Status Updated: {full_status}") # For debugging status updates

    def render_current_page_or_question(self):
        """
        Renders the current page or question based on the navigation mode.

        Fetches the appropriate content (page image or question representation)
        from the PdfEngine, converts it to a displayable format, and updates
        the main canvas. Also updates the status bar.
        """

        # Method attributes like current_file_name are derived by update_status_bar or within logic.
        # status_message_detail = ""
        # action_description = ""  # For print logging

        # Clear any old text items from canvas, except the image item itself

        for item in self.display_canvas.find_all():
            self.display_canvas.delete(item)
        #     if item not in [
        #         # if self.dual_display_mode in[] else "",
        #     ]:
        # self.display_canvas.delete(self.canvas_image_item_2)

        # Method attributes like current_file_name are derived by update_status_bar or within logic.
        surface = None
        general_render_message = ""  # Specific message for this render action

        # Clear any old text items from canvas, except the image item itself

        # for item in self.display_canvas.find_all():
        #     if item not in  [self.canvas_image_item, self.canvas_image_item_2]  :
        #         self.display_canvas.delete(item)

        if (
            not self.engine.current_pdf_document
            or not self.engine.get_current_file_path()
        ):
            self.display_canvas.itemconfig(self.canvas_image_item, image=None)
            self.display_canvas.itemconfig(
                self.canvas_image_item_2, image=None
            )
            self._photo_image_ref = None
            self.display_canvas.config(scrollregion=(0, 0, 0, 0))
            self.update_status_bar("No PDF loaded.")
            self.update_all_button_states()
            return

        # Update status before attempting render, indicating action
        # self.update_status_bar(f"Rendering {self.navigation_mode}...") # This will be more specific below

        try:

            # ren = self.engine.renderer
            # ren.set_clean_mode(ren.O_CLEAN_HEADER_FOOTER)
            q_content = ""
            # if self.navigation_mode == "ocr-md":
            #     if not self.md_
            if self.navigation_mode == "page":
                if self.current_page_number > 0 and self.total_pages > 0:
                    self.update_status_bar(
                        f"Rendering Page {self.current_page_number}/{self.total_pages}..."
                    )
                    surface = self.engine.render_pdf_page(
                        self.current_page_number, debug=0
                    )
                    general_render_message = (
                        "Page displayed."
                        if surface
                        else "Failed to render page."
                    )
                else:
                    general_render_message = (
                        "No page selected or PDF has no pages."
                    )
            elif self.navigation_mode == "question":
                if (
                    self.current_question_number > 0
                    and self.total_questions > 0
                    and self.questions_list
                ):
                    self.update_status_bar(
                        f"Rendering Question {self.current_question_number}/{self.total_questions}..."
                    )

                    surface = self.engine.render_a_question(
                        self.current_question_number, devide=False
                    )

                    if (
                        surface is None
                        and self.current_question_number - 1
                        < len(self.questions_list)
                    ):  # Fallback
                        current_q = self.questions_list[
                            self.current_question_number - 1
                        ]
                        q_text = ""
                        if current_q.pages:
                            page_to_render = current_q.pages[0]
                            self.update_status_bar(
                                f"Fallback: Rendering Page {page_to_render} for Q{self.current_question_number}."
                            )
                            surface = self.engine.render_pdf_page(
                                page_to_render, debug=0
                            )
                    else:
                        q = self.questions_list[
                            self.current_question_number - 1
                        ]
                        q_text = q.__str__()
                        q_content = "\n".join([str(c) for c in q.contents])
                    general_render_message = (
                        f"Question displayed.\n{q_text}"
                        if surface
                        else "Failed to render question."
                        + self.engine.question_detector
                    )

                    if surface is None:
                        general_render_message += (
                            " (Not available/Fallback failed)"
                        )
                else:
                    general_render_message = (
                        "No question selected or no questions available."
                    )

            print(
                general_render_message + "\nContent:\n" + q_content
            )  # Print what was attempted/result

            if surface:
                self.current_surface = surface

                class event_c:
                    width = self.display_canvas.winfo_width()
                    height = self.display_canvas.winfo_height()

                self.convert_cairo_surface_to_photoimage(surface)
                #
                # self.display_canvas.itemconfig(
                #     self.canvas_image_item, image=self._photo_image_ref
                # )
                # self.display_canvas.coords(self.canvas_image_item, 0, 0)
                # box1 = self.display_canvas.bbox(self.canvas_image_item)
                #
                # if self.img_copy_2:  # self.ocr_mode == "md":
                #     self._photo_image_ref_2 = ImageTk.PhotoImage(
                #         self.img_copy_2.copy()
                #     )
                #     self.display_canvas.itemconfig(
                #         self.canvas_image_item_2, image=self._photo_image_ref_2
                #     )
                #     self.display_canvas.coords(
                #         self.canvas_image_item_2, event_c.width // 2, 0
                #     )
                #     box2 = self.display_canvas.bbox(self.canvas_image_item_2)
                #     box = [0, 0, box2[2], max(box2[3], box1[3])]
                # else:
                #     box = box1
                # self.display_canvas.config(scrollregion=box)

                self.display_canvas.bind("<Configure>", self._resize_image)

                self._resize_image(event_c, only_resize=False)

            else:
                self.display_canvas.itemconfig(
                    self.canvas_image_item, image=None
                )

                self._photo_image_ref = None

                self.display_canvas.itemconfig(
                    self.canvas_image_item_2, image=None
                )
                self._photo_image_ref_2 = None
                self.display_canvas.config(scrollregion=(0, 0, 0, 0))

            self.update_status_bar(
                general_render_message
            )  # Final status update

        except Exception as e:
            error_msg = f"Error rendering {self.navigation_mode}: {e}"
            print(traceback.format_exc())
            print(error_msg)
            self.update_status_bar(error_msg)
            self.display_canvas.itemconfig(self.canvas_image_item, image=None)
            self._photo_image_ref = None
            self.display_canvas.itemconfig(
                self.canvas_image_item_2, image=None
            )
            self._photo_image_ref_2 = None
            self.display_canvas.config(scrollregion=(0, 0, 0, 0))

        self.update_all_button_states()

    def change_dual_mode(self, mode):

        for item in self.display_canvas.find_all():
            self.display_canvas.delete(item)

        if not self.img_copy_2 and mode == 2:
            msg = (
                "can't set mode == 2 , no img_copy_2 available, fallback == 1"
            )
            self.dual_display_mode = 1
        else:
            self.dual_display_mode = mode
            msg = "dual display mode == " + str(mode)
        print(msg)
        self.update_status_bar(msg)

        class event_c:
            width = self.display_canvas.winfo_width()
            height = self.display_canvas.winfo_height()

        self._resize_image(event_c, only_resize=False)

    def _resize_image(self, event: tk.Event, only_resize=True):
        _canvas = self.display_canvas
        try:
            target_width = event.width
            target_height = event.height

            if self.dual_display_mode == 3:
                target_width //= 2

            im1 = None
            if self.dual_display_mode in [1, 3] and self.img_copy:
                im1 = self._resize_img_copy(
                    self.img_copy, target_width, target_height, self.rel_scale
                )
                self._photo_image_ref = ImageTk.PhotoImage(im1)

                if only_resize:
                    _canvas.itemconfig(
                        self.canvas_image_item, image=self._photo_image_ref
                    )
                else:
                    self.canvas_image_item = self.display_canvas.create_image(
                        0, 0, anchor=tk.NW, image=self._photo_image_ref
                    )
                self.display_canvas.coords(self.canvas_image_item, 0, 0)
            # else:
            #     _canvas.itemconfig(self.canvas_image_item, image=None)
            #     not only_resize and

            im2 = None
            if self.dual_display_mode in [2, 3] and self.img_copy_2:
                im2 = self._resize_img_copy(
                    self.img_copy_2,
                    target_width,
                    target_height,
                    self.rel_scale_2,
                )
                self._photo_image_ref_2 = ImageTk.PhotoImage(im2)

                if only_resize and self._photo_image_ref_2:
                    _canvas.itemconfig(
                        self.canvas_image_item_2, image=self._photo_image_ref_2
                    )
                else:
                    self.canvas_image_item_2 = (
                        self.display_canvas.create_image(
                            0, 0, anchor=tk.NW, image=self._photo_image_ref_2
                        )
                    )

                x_pos = target_width if self.dual_display_mode == 3 else 0

                self.display_canvas.coords(self.canvas_image_item_2, x_pos, 0)
            # else:
            #     _canvas.itemconfig(self.canvas_image_item_2, image=None)

            _canvas.config(
                scrollregion=(
                    0,
                    0,
                    event.width,
                    max(im1.height if im1 else 0, im2.height if im2 else 0),
                )
            )

        except Exception as e:
            print(traceback.format_exc())
            raise Exception(e)

    def _resize_img_copy(
        self, img_copy, target_width, target_height, rel_scale
    ):
        width = img_copy.width or 100
        height = img_copy.height or 100 * rel_scale

        # if width > target_width:
        width = target_width
        height = int(width / rel_scale)

        # if height > target_height:
        #     height = target_height
        #     width = int(height * rel_scale)

        image = img_copy.resize((width, height))
        return image

    def convert_cairo_surface_to_photoimage(
        self, surface: cairo.ImageSurface
    ) -> ImageTk.PhotoImage | None:
        """
        Converts a Cairo ImageSurface to a Tkinter PhotoImage.

        Args:
            surface (cairo.ImageSurface): The Cairo surface to convert.

        Returns:
            ImageTk.PhotoImage | None: The converted PhotoImage, or None if conversion fails
                                      or the input surface is None. Returns a placeholder error
                                      image if conversion encounters issues.
        """
        if surface is None:
            print(
                "convert_cairo_surface_to_photoimage: Received None surface."
            )
            return None

        width = surface.get_width()
        height = surface.get_height()
        stride = surface.get_stride()
        cairo_format = surface.get_format()

        try:
            data_buffer = (
                surface.get_data()
            )  # Get data after checking surface is not None
        except (
            Exception
        ) as e:  # Underlying surface might be bad (e.g. after PDF error)
            print(f"Error getting data from Cairo surface: {e}")
            pil_image = Image.new(
                "RGB", (max(1, width), max(1, height)), color="purple"
            )  # Use max(1,...) for 0-size
            from PIL import ImageDraw  # Local import for error case

            temp_draw = ImageDraw.Draw(pil_image)
            temp_draw.text((10, 10), f"Surface Data Error: {e}", fill="white")
            return ImageTk.PhotoImage(pil_image)

        try:
            if cairo_format == cairo.FORMAT_ARGB32:
                pil_image = Image.frombytes(
                    "RGBA",
                    (width, height),
                    data_buffer.tobytes(),
                    "raw",
                    "BGRA",
                    stride,
                )
            elif cairo_format == cairo.FORMAT_RGB24:
                pil_image = Image.frombytes(
                    "RGB",
                    (width, height),
                    data_buffer.tobytes(),
                    "raw",
                    "BGRX",
                    stride,
                )
            else:
                error_msg = f"Unsupported Cairo format: {cairo_format}."
                print(error_msg)
                pil_image = Image.new("RGB", (width, height), color="red")
                from PIL import ImageDraw  # Local import for error case

                temp_draw = ImageDraw.Draw(pil_image)
                temp_draw.text((10, 10), error_msg, fill="white")

            # if self.layout_detection == 1:
            #     pil_image = self.detect_layout_yolo(pil_image)

            if 7 > self.layout_detection >= 2:
                img_bytes = self.image_to_png_bytes(self.current_surface)
                pil_image = self.detect_layout_miner_u_remote(
                    img_bytes, self.layout_detection
                )

            self.img_copy = pil_image.copy()
            self.rel_scale = pil_image.width / pil_image.height

        except Exception as e:
            error_msg = f"Error converting Cairo surface to PhotoImage: {e}"
            print(traceback.format_exc())
            print(error_msg)
            pil_image = Image.new(
                "RGB", (max(1, width), max(1, height)), color="orange"
            )
            from PIL import ImageDraw  # Local import for error case

            temp_draw = ImageDraw.Draw(pil_image)
            temp_draw.text((10, 10), error_msg, fill="black")

            self.img_copy = pil_image.copy()
            self.rel_scale = pil_image.width / pil_image.height

    def toggle_ocr_md(self, mode):

        self.update_status_bar("OCRing ......")
        self.ocr_mode = "md"
        self.img_copy_2 = None
        self.dual_display_mode = 3
        # if self.dual_display_mode =:
        # self.ocr_mode = ""
        # self.dual_display_mode = 1
        # self.img_copy_2 = None
        # # self._photo_image_ref_2 = None
        # self.render_current_page_or_question()
        # self.update_status_bar("[CLOSED] the OCR.md Mode ")
        # return

        ocr_out_path = sep.join([".", "output", "ocr_md.png"])

        if self.navigation_mode == "page":
            self.update_status_bar("Simple Ocr ...")
            self.simple_ocr(ocr_out_path)
        else:
            self.update_status_bar("Advance Ocr ...")
            ok = self.advance_ocr(ocr_out_path, mode)
            if not ok:
                return

        img = Image.open(ocr_out_path)
        self.rel_scale_2 = img.width / img.height
        self.img_copy_2 = img
        self.canvas_image_item_2 = self.display_canvas.create_image(
            0, 0, anchor=tk.NW, image=None
        )
        self.render_current_page_or_question()
        self.update_status_bar("[OPENED] the OCR.md Mode")
        pass

    def simple_ocr(self, ocr_out_path):
        img_bytes = self.image_to_png_bytes(self.current_surface)
        bytes_content = self.detect_layout_miner_u_remote(img_bytes, 7)
        zip_dict = self.expand_zip_in_memory(bytes_content)
        render_markdown_to_png(zip_dict, ocr_out_path)
        return True

    def advance_ocr(self, ocr_out_path, mode):
        surf_res = self.engine.render_a_question(
            self.current_question_number, devide=True
        )
        q = self.engine.question_list[self.current_question_number - 1]
        idx_list = []
        all_bytes = b""
        seperator = b"IAM_A_SEPERATOR_PLEASE"
        for id, surf in surf_res.items():
            idx_list.append(id)
            all_bytes += self.image_to_png_bytes(surf) + seperator

        ocr_res = self.detect_layout_miner_u_remote_advance(
            all_bytes, seperator, idx_list, mode
        )
        temp_f = "." + sep + "output" + sep + "ocr_res.json"
        self.example_counter += 1

        with open(temp_f, "w", encoding="utf-8") as f:
            f.write(json.dumps(ocr_res))

        self.update_status_bar("OCR: responce  saved to :" + temp_f)
        p_size = ocr_res.get("page-size")

        self.ocr_question_processor.set_question(q, ocr_res, surf_res, p_size)
        css_path = (
            Path(os.path.join("resources", "question.css")).resolve().as_uri()
        )

        template = f"""

                <!DOCTYPE html>
                <html>

                <head>
                  <title>MathJax TeX Test Page</title>
                  <link rel="stylesheet" href="{css_path}">
                  <script type="text/javascript" id="MathJax-script" async
                    src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js">
                    </script>
                </head>

                <body>
                    {self.ocr_question_processor.html}
                </body>

                </html>
        """

        temp_html = OcrItem.OCR_OUTPUT_DIR + sep + f"{q.id}.html"

        with open(temp_html, "w", encoding="utf-8") as f:
            f.write(template)

        self.update_status_bar(
            "OCR: result parsed successfully , saved to :" + temp_html
        )

        if os.name == "nt":  # Windows
            asyncio.set_event_loop_policy(
                asyncio.WindowsSelectorEventLoopPolicy()
            )

        asyncio.run(self.render_html_playwright(temp_html, ocr_out_path))

        self.update_status_bar("html rendered successfully")
        return True

    def expand_zip_in_memory(self, zip_bytes):
        in_memory_zip = io.BytesIO(zip_bytes)
        with open("output/temp.zip", "wb") as fb:
            fb.write(zip_bytes)
        with zipfile.ZipFile(in_memory_zip, "r") as zip_ref:
            return {name: zip_ref.read(name) for name in zip_ref.namelist()}

    async def render_html_playwright(
        self, input_html_path: dict, output_png_path: str
    ):
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch()

                page = await browser.new_page()

                await page.set_viewport_size(
                    {
                        "width": self.engine.scaled_page_width
                        // self.engine.scaling
                        * 2,
                        "height": 1,
                        # self.engine.scaled_page_height // self.engine.scaling * 2,
                    }
                )

                await page.goto(Path(input_html_path).resolve().as_uri())

                # await page.add_style_tag(content=css2)

                await page.wait_for_load_state("networkidle")

                await page.screenshot(
                    path=output_png_path, full_page=True, type="png"
                )
                # await browser.close()

            print(f"✅ Successfully rendered content to {output_png_path}")

        finally:
            print("Playwright : finished taking the screen shot")

    def toggle_ocr_tex(self, event=None):
        pass

    def detect_layout_miner_u_remote_advance(
        self, all_bytes: bytes, seperator: bytes, idx_list, mode: int
    ):
        data = {
            "idx": idx_list,
            "seperator": seperator.decode("latin"),
            "mode": "pipeline" if mode == 1 else "transformers",
        }
        files = {
            "image": (
                "some_name.png",
                all_bytes,
                "image/png",
            )
        }
        res = requests.post(
            KAGGLE_SERVER_URL + "/advance",
            files=files,
            data={"json": json.dumps(data)},
        )
        return res.json()

    def detect_layout_miner_u_remote(self, img_bytes: str, mode: str):
        want = "md_content.md" if mode == 7 else f"draw{mode}.png"
        data = {
            "exam": self.engine.pdf_name,
            "display-mode": self.navigation_mode,
            "number": (
                self.current_page_number
                if self.navigation_mode == "page"
                else self.current_question_number
            ),
            "want": want,
        }
        files = {
            "image": (
                "some_name.png",
                img_bytes,
                "image/png",
            )
        }

        res = requests.post(
            KAGGLE_SERVER_URL, files=files, data=data
        )  # timeout=60 60-second timeout

        if mode != 7:
            return Image.open(io.BytesIO(res.content))
        else:
            return res.content

    # def detect_layout_miner_u_old(self, input_file: str):
    #
    #     from magic_pdf.data.data_reader_writer import (
    #         FileBasedDataWriter,
    #         FileBasedDataReader,
    #     )
    #     from magic_pdf.data.dataset import ImageDataset
    #     from magic_pdf.model.doc_analyze_by_custom_model import doc_analyze
    #     from magic_pdf.data.read_api import read_local_images
    #     from magic_pdf.operators.models import InferenceResult, PipeResult
    #     from magic_pdf.tools.common import do_parse
    #
    #     # prepare env
    #     local_image_dir, local_md_dir = "output/images", "output"
    #     image_dir = str(os.path.basename(local_image_dir))
    #
    #     os.makedirs(local_image_dir, exist_ok=True)
    #
    #     image_writer, md_writer = FileBasedDataWriter(
    #         local_image_dir
    #     ), FileBasedDataWriter(local_md_dir)
    #
    #     lang = "ch"
    #     reader = FileBasedDataReader()
    #     ds = ImageDataset(reader.read(input_file), lang=lang)
    #
    #     inf_res: InferenceResult = ds.apply(
    #         doc_analyze,
    #         ocr=True,
    #         lang=lang,
    #         show_log=True,
    #     )
    #
    #     pip_res: PipeResult = inf_res.pipe_ocr_mode(image_writer, lang=lang)
    #
    #     pip_res.dump_md(md_writer, f"testing_miner_u.md", image_dir)
    #     output_file = sep.join([".", "output", "gui_temp_image.pdf"])
    #     if self.layout_detection == 2:
    #         print("mode == 2")
    #         pip_res.draw_layout(output_file)
    #     elif self.layout_detection == 3:
    #         print("mode == 3")
    #         pip_res.draw_span(output_file)
    #     elif self.layout_detection == 4:
    #         print("mode == 3")
    #         pip_res.draw_line_sort(output_file)
    #     else:
    #         raise Exception("Invalid mode")
    #
    #     dpi = 150
    #     doc = fitz.open(output_file)
    #     page = doc.load_page(0)
    #     pix = page.get_pixmap(dpi=dpi)
    #     mode = "RGBA" if pix.alpha else "RGB"
    #     img = Image.frombytes(mode, (pix.width, pix.height), pix.samples)
    #     doc.close()
    #
    #     return img
    #

    # def detect_layout_yolo(self, pil_image):
    #     from doclayout_yolo import YOLOv10
    #     model = YOLOv10(
    #         sep.join(
    #             [
    #                 ".",
    #                 "local-models",
    #                 "yolo",
    #                 "doclayout_yolo_docstructbench_imgsz1024.pt",
    #             ]
    #         )
    #     )
    #     img = pil_image
    #
    #     det_res = model.predict(
    #         img,
    #         imgsz=1024,
    #
    #         conf=0.2,
    #         device="cpu",
    #     )
    #     annotated_frame: NDArray = det_res[0].plot(
    #         pil=True,
    #         line_width=1 * self.engine.scaling,
    #         font_size=20 * self.engine.scaling,
    #     )
    #     pil_image = Image.fromarray(annotated_frame)
    #     return pil_image

    def debug_current_item(self, event=None, combined_debug=False):
        """
        Performs debug operations on the current item (page or questions).

        Args:
            event (tk.Event, optional): Event that triggered the call (e.g., keyboard shortcut).
                                       Defaults to None.
            combined_debug (bool, optional): If True, performs combined debug (extract questions
                                             then render a page with debug flags). Otherwise,
                                             performs standard debug based on current mode.
                                             Defaults to False.
        """
        if not self.engine.current_pdf_document:
            self.update_status_bar("No PDF loaded to debug.")
            self.display_canvas.itemconfig(self.canvas_image_item, image=None)
            self._photo_image_ref = None
            self.display_canvas.config(scrollregion=(0, 0, 0, 0))
            return

        surface = None
        general_debug_message = ""

        try:
            if not combined_debug:
                if self.navigation_mode == "page":
                    if self.current_page_number > 0:
                        self.update_status_bar(
                            f"Debugging Page {self.current_page_number}..."
                        )
                        surface = self.engine.render_pdf_page(
                            self.current_page_number, debug=self.engine.M_DEBUG
                        )
                        general_debug_message = (
                            f"Debugged Page {self.current_page_number}."
                        )
                    else:
                        general_debug_message = "No page selected to debug."
                elif self.navigation_mode == "question":
                    print("navigation_mode == question")
                    self.update_status_bar(
                        "Debugging Questions (extraction)..."
                    )
                    self.questions_list = (
                        self.engine.extract_questions_from_pdf(
                            debug=self.engine.M_DEBUG
                        )
                    )
                    self.total_questions = (
                        len(self.questions_list) if self.questions_list else 0
                    )
                    if (
                        self.current_question_number > self.total_questions
                        or (
                            self.current_question_number == 0
                            and self.total_questions > 0
                        )
                    ):
                        self.current_question_number = (
                            1 if self.total_questions > 0 else 0
                        )

                    general_debug_message = "Debugged Questions (extraction)."
                    if (
                        self.current_question_number > 0
                        and self.total_questions > 0
                    ):
                        general_debug_message += (
                            f" Current Q{self.current_question_number}."
                        )

                    # Refresh main display based on (potentially) new question data.
                    # This call will also handle its own status update regarding rendering.
                    self.render_current_page_or_question()
                    # Then, set the specific debug general message.
                    self.update_status_bar(general_debug_message)
                    self.update_all_button_states()
                    return  # Return early as render_current_page_or_question handles display & its status
            else:  # Combined Debug
                self.update_status_bar(
                    "Combined Debug: Extracting questions..."
                )
                self.questions_list = self.engine.extract_questions_from_pdf(
                    debug=self.engine.M_DEBUG
                )
                self.total_questions = (
                    len(self.questions_list) if self.questions_list else 0
                )
                if self.current_question_number > self.total_questions or (
                    self.current_question_number == 0
                    and self.total_questions > 0
                ):
                    self.current_question_number = (
                        1 if self.total_questions > 0 else 0
                    )

                page_to_debug = 1
                if (
                    self.navigation_mode == "page"
                    and self.current_page_number > 0
                ):
                    page_to_debug = self.current_page_number
                elif (
                    self.navigation_mode == "question"
                    and self.current_question_number > 0
                    and self.questions_list
                ):
                    try:
                        current_q = self.questions_list[
                            self.current_question_number - 1
                        ]
                        if current_q.pages:
                            page_to_debug = current_q.pages[0]
                        else:
                            print(
                                f"Warning: Q{self.current_question_number} has no 'pages'. Defaulting page 1 for debug."
                            )
                    except IndexError:
                        print(
                            f"Error: Q_idx {self.current_question_number} out of bounds. Defaulting page 1 for debug."
                        )
                    except AttributeError:
                        print(
                            "Error: Question object missing 'pages'. Defaulting page 1 for debug."
                        )

                self.update_status_bar(
                    f"Combined Debug: Rendering page {page_to_debug}..."
                )
                surface = self.engine.render_pdf_page(
                    page_to_debug, debug=self.engine.M_DEBUG
                )
                general_debug_message = f"Combined Debug: Questions extracted & Page {page_to_debug} debugged."

            # Common surface handling for non-question-extraction debug or combined page debug
            if surface:

                self.convert_cairo_surface_to_photoimage(surface)
                self._photo_image_ref = ImageTk.PhotoImage(self.pil_image)

                self.display_canvas.itemconfig(
                    self.canvas_image_item, image=self._photo_image_ref
                )
                self.display_canvas.coords(self.canvas_image_item, 0, 0)
                self.display_canvas.config(
                    scrollregion=self.display_canvas.bbox(
                        self.canvas_image_item
                    )
                )
            elif not (
                not combined_debug and self.navigation_mode == "question"
            ):
                self.display_canvas.itemconfig(
                    self.canvas_image_item, image=None
                )
                self._photo_image_ref = None
                self.display_canvas.config(scrollregion=(0, 0, 0, 0))

            # If combined debug, after potentially displaying the debugged page surface,
            # refresh the main display to be consistent with the current navigation mode and item.
            # The debugged page surface takes precedence for one-time view if generated.
            if combined_debug:
                if (
                    not surface
                ):  # If combined debug didn't produce a direct page surface to display.
                    self.render_current_page_or_question()  # This will set its own status.
                # The general_debug_message for combined debug will be set as the final status.

            self.update_status_bar(general_debug_message)

        except Exception as e:
            error_msg = f"Error during debug: {e}"
            print(traceback.format_exc())
            print(error_msg)
            self.update_status_bar(error_msg)
            self.display_canvas.itemconfig(self.canvas_image_item, image=None)
            self._photo_image_ref = None
            self.display_canvas.config(scrollregion=(0, 0, 0, 0))

        self.update_all_button_states()

    def reload_engine_code(self, event=None):
        """
        Reloads the PdfEngine module and re-initializes the engine instance.

        Attempts to preserve and restore the current viewing state (PDF file,
        page/question number, mode) after the reload.

        Args:
            event (tk.Event, optional): Event that triggered the call. Defaults to None.
        """
        print("Attempting to reload PDF Engine module...")
        current_pdf_path = None
        current_page = self.current_page_number
        current_question = self.current_question_number
        current_mode = self.navigation_mode
        all_pdf_paths = list(self.engine.all_pdf_paths)  # Make a copy
        current_pdf_idx = self.engine.current_pdf_index
        original_scaling = (
            self.engine.scaling
        )  # Assuming scaling is an attribute

        if (
            self.engine.current_pdf_document
            and self.engine.get_current_file_path()
        ):
            current_pdf_path = self.engine.get_current_file_path()
            # current_pdf_name = os.path.basename(current_pdf_path) # Not strictly needed for restore

        try:
            self.update_status_bar("Reloading engine module...")
            for module in ALL_MODULES:
                importlib.reload(module)
            print("PDF Engine module reloaded.")

            self.update_status_bar("Re-initializing PDF Engine...")
            self.engine = pdf_engine_module.PdfEngine(scaling=original_scaling)
            print("PDF Engine re-initialized.")

            self.update_status_bar("Engine re-initialized. Restoring state...")
            # Reset GUI state that depends on engine instance details not yet restored
            self.total_pages = 0
            self.current_page_number = 0
            self.total_questions = 0
            self.current_question_number = 0
            self.questions_list = []

            if all_pdf_paths:
                self.engine.set_files(all_pdf_paths)  # Restore file list

                if (
                    current_pdf_path and current_pdf_idx != -1
                ):  # Check if a PDF was actually loaded
                    # Try to restore to the previously active PDF
                    # process_next_pdf_file increments index *before* loading.
                    # So, to load current_pdf_idx, we need to set index to current_pdf_idx - 1.
                    self.engine.current_pdf_index = current_pdf_idx - 1

                    if (
                        self.engine.proccess_next_pdf_file()
                    ):  # This should load the PDF at current_pdf_idx
                        print(
                            f"Successfully reloaded and processed: {self.engine.get_current_file_path()}"
                        )
                        self.total_pages = (
                            self.engine.get_num_pages()
                            if self.engine.current_pdf_document
                            else 0
                        )

                        if current_mode == "page":
                            self.navigation_mode = "page"
                            self.current_page_number = (
                                min(current_page, self.total_pages)
                                if self.total_pages > 0
                                else 0
                            )
                            if (
                                self.current_page_number == 0
                                and self.total_pages > 0
                            ):
                                self.current_page_number = 1

                        elif current_mode == "question":
                            # switch_to_question_mode will try to extract questions
                            self.switch_to_question_mode()  # This sets nav_mode and extracts questions
                            self.current_question_number = (
                                min(current_question, self.total_questions)
                                if self.total_questions > 0
                                else 0
                            )
                            if (
                                self.current_question_number == 0
                                and self.total_questions > 0
                            ):
                                self.current_question_number = 1

                        # render_current_page_or_question will call update_status_bar with item details.
                        self.render_current_page_or_question()
                        self.update_status_bar(
                            f"Engine reloaded. Restored state for {os.path.basename(current_pdf_path)}."
                        )
                    else:
                        self.render_current_page_or_question()
                        self.update_status_bar(
                            "Engine reloaded. Could not restore previous PDF."
                        )
                else:
                    self.render_current_page_or_question()
                    self.update_status_bar(
                        "Engine reloaded. No active PDF to restore. File list restored if any."
                    )
            else:
                self.render_current_page_or_question()
                self.update_status_bar(
                    "Engine reloaded. No previous PDF list to restore."
                )

        except Exception as e:
            error_message = f"Error reloading engine: {e}"
            print(traceback.format_exc())
            print(error_message)  # Keep console print for dev
            self.update_status_bar(f"Critical error reloading engine: {e}")
            # Potentially, the engine is in a bad state. Could try to revert to a new clean instance.
            # For now, just report error. User might need to restart if it's critical.

        self.update_all_button_states()

    def on_new_pdf_or_item(self):
        self.layout_detection = False
        # self.dual_display_mode = 1
        if self.dual_display_mode == 2:
            self.dual_display_mode = 1
        self.img_copy_2 = None

    def next_pdf_file(self):
        """
        Loads and displays the next PDF file in the list.
        Resets view to page mode and first page. Updates status and button states.
        """

        if self.engine.proccess_next_pdf_file():

            self.on_new_pdf_or_item()
            self.navigation_mode = "page"  # Default to page mode on new PDF
            self.total_pages = (
                self.engine.get_num_pages()
                if self.engine.current_pdf_document
                else 0
            )
            self.current_page_number = 1 if self.total_pages > 0 else 0
            self.total_questions = 0  # Reset questions for new PDF
            self.current_question_number = 0
            self.questions_list = []
            en = self.engine
            self.ocr_question_processor = OcrQuestion(
                en.scaled_page_width,
                en.scaled_page_height,
                en.line_height,
                en.scaling,
            )
            self.render_current_page_or_question()
        else:
            # self.total_pages = 0
            # self.current_page_number = 0
            # self.total_questions = 0
            # self.current_question_number = 0
            # self.render_current_page_or_question()  # Will show "No PDF" or similar & update status
            self.update_status_bar(
                "End of PDF list."
            )  # Explicitly set general message
        self.update_all_button_states()

    def previous_pdf_file(self):
        """
        Loads and displays the previous PDF file in the list.
        Resets view to page mode and first page. Updates status and button states.
        """

        if not self.engine.all_pdf_paths:
            self.render_current_page_or_question()  # Shows "No PDF"
            self.update_status_bar("No PDF files loaded.")
            self.update_all_button_states()
            return

        if self.engine.proccess_prev_pdf_file():

            self.on_new_pdf_or_item()

            self.navigation_mode = "page"
            self.total_pages = (
                self.engine.get_num_pages()
                if self.engine.current_pdf_document
                else 0
            )
            self.current_page_number = 1 if self.total_pages > 0 else 0
            self.total_questions = 0  # Reset questions for new PDF
            self.current_question_number = 0
            self.questions_list = []
            self.render_current_page_or_question()
        else:
            # Already at the beginning, no change in PDF, but refresh status
            self.render_current_page_or_question()
            self.update_status_bar("At the beginning of PDF list.")

        self.update_all_button_states()

    def switch_to_page_mode(self, event=None):
        """
        Switches the navigation mode to "page".
        Updates display to show the current page. Refreshes status and button states.

        Args:
            event (tk.Event, optional): Event that triggered the call. Defaults to None.
        """
        if self.navigation_mode == "page":
            self.update_status_bar("Already in Page Mode.")
            return

        self.on_new_pdf_or_item()
        print("Switching to Page Mode")
        self.navigation_mode = "page"
        if not self.engine.current_pdf_document or self.total_pages == 0:
            self.current_page_number = 0
        elif self.current_page_number == 0 and self.total_pages > 0:
            self.current_page_number = 1

        self.render_current_page_or_question()
        self.update_status_bar(
            "Switched to Page Mode."
        )  # General confirmation
        self.update_all_button_states()

    def switch_to_question_mode(self, event=None):
        """
        Switches the navigation mode to "question".
        Extracts questions from the current PDF if not already done.
        Updates display to show the current question. Refreshes status and button states.

        Args:
            event (tk.Event, optional): Event that triggered the call. Defaults to None.
        """
        if self.navigation_mode == "question":
            self.update_status_bar("Already in Question Mode.")
            return

        self.on_new_pdf_or_item()

        print("Switching to Question Mode")
        self.navigation_mode = "question"

        if self.engine.current_pdf_document:
            try:

                self.update_status_bar("Extracting questions...")

                # ren = self.engine.renderer
                # ren.set_clean_mode(ren.O_CLEAN_HEADER_FOOTER)
                self.questions_list = self.engine.extract_questions_from_pdf()
                self.total_questions = (
                    len(self.questions_list) if self.questions_list else 0
                )
                self.current_question_number = (
                    1 if self.total_questions > 0 else 0
                )
                if self.total_questions == 0:
                    print("No questions found in the PDF.")
                    self.update_status_bar("No questions found in this PDF.")
                else:
                    # render_current_page_or_question will show item details
                    self.update_status_bar(
                        f"Switched to Question Mode. {self.total_questions} questions found."
                    )
            except Exception as e:
                error_msg = f"Error extracting questions: {e}"
                print(traceback.format_exc())
                print(error_msg)
                self.update_status_bar(error_msg)
                self.questions_list = []
                self.total_questions = 0
                self.current_question_number = 0
        else:
            self.questions_list = []
            self.total_questions = 0
            self.current_question_number = 0
            self.update_status_bar("No PDF loaded to extract questions from.")

        self.render_current_page_or_question()
        self.update_all_button_states()

    def next_item(self):
        """
        Navigates to the next item (page or question) based on the current mode.
        Updates display, status, and button states.
        """
        if not self.engine.current_pdf_document:
            self.update_status_bar("No PDF loaded to navigate items.")
            return

        self.on_new_pdf_or_item()

        changed = False
        if self.navigation_mode == "page":
            if self.current_page_number < self.total_pages:
                self.current_page_number += 1
                changed = True
        elif self.navigation_mode == "question":
            if self.current_question_number < self.total_questions:
                self.current_question_number += 1
                changed = True

        if changed:
            self.render_current_page_or_question()  # Handles status update for item change
        else:
            self.update_status_bar(
                f"Already at the last {self.navigation_mode}."
            )
        self.update_all_button_states()

    def previous_item(self):
        """
        Navigates to the previous item (page or question) based on the current mode.
        Updates display, status, and button states.
        """
        if not self.engine.current_pdf_document:
            self.update_status_bar("No PDF loaded to navigate items.")
            return

        self.on_new_pdf_or_item()

        changed = False
        if self.navigation_mode == "page":
            if self.current_page_number > 1:
                self.current_page_number -= 1
                changed = True
        elif self.navigation_mode == "question":
            if self.current_question_number > 1:
                self.current_question_number -= 1
                changed = True

        if changed:
            self.render_current_page_or_question()  # Handles status update for item change
        else:
            self.update_status_bar(
                f"Already at the first {self.navigation_mode}."
            )
        self.update_all_button_states()

    def update_all_button_states(self):
        """
        Updates the enabled/disabled state of all navigation and mode buttons
        based on the current application state (loaded PDF, current item, mode, etc.).
        """
        num_files = len(self.engine.all_pdf_paths)
        current_pdf_idx = self.engine.current_pdf_index
        pdf_loaded = self.engine.current_pdf_document is not None

        # PDF Navigation Buttons
        self.next_pdf_button.config(
            state=(
                tk.NORMAL
                if num_files > 0 and current_pdf_idx < num_files - 1
                else tk.DISABLED
            )
        )
        self.prev_pdf_button.config(
            state=(
                tk.NORMAL
                if num_files > 0 and current_pdf_idx > 0
                else tk.DISABLED
            )
        )

        # Mode Switching Buttons
        self.page_mode_button.config(
            state=tk.DISABLED if self.navigation_mode == "page" else tk.NORMAL
        )
        self.question_mode_button.config(
            state=(
                tk.DISABLED
                if self.navigation_mode == "question"
                else tk.NORMAL
            )
        )
        if not pdf_loaded:  # Disable mode switching if no PDF
            self.page_mode_button.config(state=tk.DISABLED)
            self.question_mode_button.config(state=tk.DISABLED)

        # Item Navigation Buttons
        if pdf_loaded:
            if self.navigation_mode == "page":
                self.next_item_button.config(
                    state=(
                        tk.NORMAL
                        if self.current_page_number < self.total_pages
                        else tk.DISABLED
                    )
                )
                self.prev_item_button.config(
                    state=(
                        tk.NORMAL
                        if self.current_page_number > 1
                        else tk.DISABLED
                    )
                )
            elif self.navigation_mode == "question":
                self.next_item_button.config(
                    state=(
                        tk.NORMAL
                        if self.current_question_number < self.total_questions
                        else tk.DISABLED
                    )
                )
                self.prev_item_button.config(
                    state=(
                        tk.NORMAL
                        if self.current_question_number > 1
                        else tk.DISABLED
                    )
                )
            else:  # Should not happen
                self.next_item_button.config(state=tk.DISABLED)
                self.prev_item_button.config(state=tk.DISABLED)
        else:  # No PDF loaded
            self.next_item_button.config(state=tk.DISABLED)
            self.prev_item_button.config(state=tk.DISABLED)


if __name__ == "__main__":
    # This assumes that 'engine' and 'PDFs' are in the right place relative to 'gui'
    # If running advanced_pdf_gui.py directly from the 'gui' folder,
    # Python's import system might need adjustment for 'engine.pdf_engine'
    # e.g. by adding the parent directory to sys.path.
    # For now, we assume the execution context is the root of the repository.
    app = AdvancedPDFViewer()
    app.mainloop()
