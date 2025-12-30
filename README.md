# Python PDF Parser & Renderer

A sophisticated, from-scratch PDF parsing and rendering engine written entirely in Python. This project implements a complete PDF processing pipeline including stream parsing, graphics state management, font handling, and Cairo-based rendering, with advanced features for educational content extraction.

## 🎯 Project Overview

This is a **production-grade PDF engine** that demonstrates deep understanding of the PDF specification (ISO 32000). Unlike libraries that wrap existing C/C++ engines, this implementation parses and renders PDFs natively in Python, providing full control over the rendering pipeline and enabling specialized features for educational content processing.

### Key Achievements
- ✅ **Complete PDF parser** with custom regex-based tokenizer
- ✅ **Sophisticated rendering engine** using Cairo graphics
- ✅ **Advanced font handling** (Type1, TrueType, Type0, partial Type3)
- ✅ **PDF graphics state machine** with full matrix transformations
- ✅ **Question detection system** for hierarchical document structure
- ✅ **Feature-rich GUI** for debugging and visualization
- ✅ **OCR integration** with modern ML models (MinerU)

## 🏗️ Architecture

### Core Engine Components

```
PdfEngine (Main Controller)
├── PDFStreamParser (Lexical Analysis)
├── EngineState (PDF State Machine)
├── BaseRenderer (Cairo Rendering)
├── PdfFont (Font System)
├── PdfOperator (Command System)
└── QuestionDetector (Semantic Analysis)
```

### Technical Sophistication

1. **PDF Stream Parser** (`pdf_stream_parser.py`)
   - Custom regex-based tokenizer handling PDF syntax quirks
   - Proper escaping for parentheses, hex strings, arrays, dictionaries
   - Inline image support with multiple compression filters

2. **Graphics State Machine** (`engine_state.py`)
   - Complete PDF graphics state (CTM, text matrix, colors, line styles)
   - Color space support (DeviceGray, DeviceRGB, DeviceCMYK)
   - Transformation matrix mathematics (3×3 matrices as 6-element arrays)
   - Graphics state stack with `q`/`Q` operators

3. **Cairo Renderer** (`pdf_renderer.py`)
   - Surface management and matrix synchronization
   - Text rendering with multiple modes (fill, stroke, clip)
   - Path operations (move, line, curve, rectangle)
   - Image decoding and color space conversion

4. **Font System** (`pdf_font.py`)
   - Embedded font extraction and FreeType integration
   - Type0 composite fonts with descendant fonts
   - Encoding mapping with `/Differences` dictionaries
   - ToUnicode CMaps for proper text extraction
   - System font fallback and substitution

5. **Question Detector** (`detectors/question_detectors.py`)
   - Hierarchical detection (questions → parts → subparts)
   - Spatial reasoning with adaptive tolerance factors
   - Multi-level label validation (numeric, alphabetic, Roman)
   - Page transition handling for multi-page questions

## 🚀 Features

### PDF Parsing & Rendering
- **From-scratch parser**: No external PDF libraries for core parsing
- **Complete operator support**: Graphics, text, color, path, and image operators
- **Matrix transformations**: Proper handling of PDF's Y-up coordinate system
- **Resource management**: Font caching, color space processing, XObject handling
- **Error resilience**: Graceful fallbacks for unsupported features

### Advanced Capabilities
- **Question extraction**: Detect hierarchical document structure in exam papers
- **OCR integration**: MinerU models for tables, images, and LaTeX equations
- **GUI debugging**: Interactive visualization of parsing and rendering pipeline
- **Automated testing**: Comprehensive test suite across multiple PDF samples
- **Performance profiling**: Detailed timing and memory usage analysis

### CLI & GUI Interfaces
- **Command-line interface**: Batch processing and automated testing
- **Advanced GUI**: Tkinter-based debugger with live code reloading
- **Dual display modes**: Side-by-side original vs OCR comparison
- **Keyboard shortcuts**: Efficient navigation and debugging workflows

## 📦 Installation

### Prerequisites
- Python ≥ 3.13
- Cairo graphics library (`libcairo2`)
- FreeType font library (`libfreetype6`)

### Quick Start
```bash
# Clone the repository
git clone https://github.com/zakir0101/python-pdf-parser-renderer.git
cd python-pdf-parser-renderer

# Install dependencies (using uv)
uv sync

# Or using pip
pip install -r requirements.txt
```

### Dependencies
Key dependencies include:
- `pycairo` - Cairo graphics bindings
- `fonttools` & `freetype-py` - Font processing
- `pymupdf` & `pypdf` - Reference PDF libraries (for comparison)
- `pillow` - Image processing
- `playwright` - HTML rendering for OCR results
- `google-genai` - Gemini API integration (optional)

## 🛠️ Usage

### Command Line Interface
```bash
# Launch the advanced GUI debugger
python main.py test gui --group latest --size small --subjects 9709

# Extract questions from a PDF
python main.py test extract-questions --path /path/to/exam.pdf

# Render specific pages
python main.py test view-page --path /path/to/exam.pdf --range 1-5

# List available exam PDFs
python main.py list exams --subjects 0580 --year 23

# Clear temporary files
python main.py clear
```

### Python API
```python
from engine.pdf_engine import PdfEngine

# Initialize the engine
engine = PdfEngine()

# Process a PDF file
engine.set_files(["/path/to/exam.pdf"])
engine.proccess_next_pdf_file()

# Extract questions
questions = engine.extract_questions_from_pdf()

# Render a specific page
surface = engine.render_pdf_page(page_number=1)

# Render a specific question
question_surface = engine.render_a_question(question_index=0)
```

### GUI Features
The advanced GUI (`gui/advanced_pdf_gui.py`) provides:
- **Page navigation**: Ctrl+P to view pages, Ctrl+Q for questions
- **Debug tools**: Ctrl+D to debug current item, Ctrl+R to reload engine
- **OCR integration**: Ctrl+M for markdown, Ctrl+L for LaTeX extraction
- **Layout detection**: Toggle YOLO/Miner-U models (Ctrl+T, Ctrl+Shift+T)
- **Dual display**: Side-by-side original vs OCR (Ctrl+W then 1/2/3)

## 📚 Technical Details

### PDF Parsing Implementation
The parser uses a sophisticated regex-based approach to handle PDF's complex syntax:
- Token replacement strategy for nested structures
- Proper handling of escaped parentheses in strings
- Support for inline images with multiple compression filters
- Recursive XObject execution with depth limiting

### Rendering Pipeline
1. **Stream parsing**: Extract PDF commands and operands
2. **State management**: Update graphics state based on operators
3. **Command execution**: Render to Cairo surface
4. **Detector invocation**: Process text commands for semantic analysis
5. **Output generation**: Save as PNG, HTML, or structured data

### Font System Architecture
- **Embedded font extraction**: Decode and save to temporary files
- **FreeType integration**: Glyph metrics and rendering
- **Encoding mapping**: Handle `/Encoding` dictionaries and `/Differences`
- **ToUnicode CMaps**: Proper Unicode mapping for text extraction
- **Fallback system**: System font substitution when embedded fonts unavailable

### Question Detection Algorithm
- **Multi-level hierarchy**: Questions → Parts → Subparts
- **Spatial validation**: X-position tolerance factors for each level
- **Label sequencing**: Validate numeric (1→2→3), alphabetic (a→b→c), Roman (i→ii→iii)
- **Error recovery**: Reset state on out-of-position labels
- **Page continuity**: Track questions across page boundaries

## 🧪 Testing & Validation

The project includes comprehensive testing:
- **Automated tests**: Across 1000+ IGCSE exam pages (2011-present)
- **Rendering validation**: Compare against PyMuPDF reference output
- **Question detection**: Accuracy testing on structured exam papers
- **Performance profiling**: Timing analysis for optimization
- **Error tracking**: Systematic collection of rendering issues

### Test Commands
```bash
# Run rendering tests
python main.py test renderer-show --group latest --size small

# Test question detection
python main.py test extract-questions --subjects 0580 9709

# Validate font handling
python main.py test font-missing --group all
```

## 🎓 Educational Focus

While this is a general-purpose PDF engine, it includes specialized features for educational content:

### IGCSE Exam Processing
- **Subject codes**: 0580 (Mathematics), 9709 (Further Mathematics), 0625 (Physics), etc.
- **Year ranges**: 2011 to present
- **Question structures**: Adapted to exam paper formatting conventions
- **OCR optimization**: Tuned for mathematical notation and diagrams

### Content Extraction Pipeline
1. **PDF parsing** → Extract drawing commands and text
2. **Question detection** → Identify hierarchical structure
3. **Image cropping** → Isolate questions and parts
4. **OCR processing** → Extract text, tables, and LaTeX
5. **Validation** → Compare original vs extracted content
6. **Export** → Generate structured output (JSON, HTML, Markdown)

## 🔧 Project Status

### ✅ Implemented
- Core PDF parsing and rendering engine
- Complete graphics state management
- Font handling (Type1, TrueType, Type0)
- Question detection system
- GUI debugging interface
- OCR integration framework

### ⚠️ Partial Implementation
- Type3 fonts (programmatically defined)
- Advanced color spaces (Patterns, Shadings)
- Transparency and blend modes
- Soft masks and advanced graphics

### 📋 Roadmap
- Performance optimization (font caching, parallel processing)
- Extended PDF feature support
- Enhanced OCR pipeline with caching
- Cloud deployment for heavy ML models
- API server for remote processing

## 🤝 Contributing

This project represents significant engineering work and deep understanding of PDF internals. Contributions are welcome in areas such as:

1. **Performance optimization**: Font caching, parallel processing
2. **PDF feature completion**: Advanced color spaces, transparency
3. **Testing infrastructure**: More comprehensive test suites
4. **Documentation**: API documentation, architecture guides
5. **Educational extensions**: Additional exam formats, subject support

## 📄 License

This project is shared as a portfolio piece demonstrating advanced Python engineering and PDF expertise. The code is available for educational and research purposes.

## 🙏 Acknowledgments

- **PDF Specification**: ISO 32000 for the comprehensive standard
- **Cairo Graphics**: For the robust 2D rendering library
- **FreeType**: For font rendering capabilities
- **IGCSE**: Cambridge International for the exam content used in testing
- **MinerU**: For the excellent OCR models used in content extraction

## 📞 Contact

For questions about the PDF engine implementation or to discuss PDF parsing/rendering techniques:

**Repository**: https://github.com/zakir0101/python-pdf-parser-renderer

---

*This project demonstrates that complex binary format parsing and rendering can be implemented successfully in pure Python, providing both educational value and practical utility for specialized PDF processing tasks.*