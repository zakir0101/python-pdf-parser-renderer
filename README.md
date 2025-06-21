# Peoject Goal

project goal was to process raw PDF fils containing exams (IGCSE) and identify
elements object in them like : questions , diagrams, tables, latex-equations ..

first step was to create a rendering engine to verify that we can capture
PDF commands and parse them correctly.

currently the rendering engine is able to render the pdf file ,but it does not use the
same embeded font in the target pdf, work has been done to enable this feature but its
not complete yet , and need fixing some minor issues [ pdf_font.py and pdf_renderer.py].

# UPDATE : 12-06-2025

## engine module:

- currently the rendering engine is capable of handling exms (now - 2011), and rendering them perfictly , but with some exceptions:
    - execpt for 1 or 2 pages contining a glyph with fonttpe3 ( which is currently only partially implemented) .
    - some old pdf dont have actual Font embedded in them , and hence we use a siutable opensource alternatives, but some glyph might (theoretically) render differently
- other some issues :
    - the rendering engine ( with exception of the parser ) is NOT optimized for performance , specially the class that handle fonts "PdfFont" which make many/some redundant calls . 
    - alot of PDf features are not supported like the different types of Colorspaces .. etc , they are not relevant to the mission of this project, and have not impact on the current exams sample
- the code is restructured for enhancing readabilty and extesebilty 
- the class PdfEngine serve as an API for the outside World

---

## detectors (QuestionDetector):

- is currently capable of detecting question, parts and subparts. its still not tested on the full dataset.but it performed well on small subset
- [depricated] its also capable of detecting lines and paragraph ( deprecated infavor of datalabs/MinerU Ocr )
- is NOT optimized for performance 
- code was restructured (to a degree) for enhancing the readabilty and maintainabilty


---
## CLI interface:

- located in main.py and cli_actions.py
- most of its functionality is [depricated] by gui/advance_pdf_gui , which offer more functionality and make the debuggin easier
- most of code need update to use the new PdfEngine API, and probarl only parts related to automated tests will be updated !

---

## the use of MinerU Ocr models:

- the models are excelent for there jobs and offer results very close to Mathpix, and [theortically] outperform Mathpix in certain area, they are opensource , can be customized (setting threshold), and they deliver low level extracted information (line/span) infos , and offer some basic heigh-level  for converting the results to markdown
- the are large to be hosted locally (need gpus), some basic server-code for running the models on cloude (tested on kaggle+flask+ngrok) can be found zakir0101/pdf-element-extraction-kaggle
- the models can detect:
    - tables and their content
    - images 
    - display math and extract latex code
    - lines and within each line 1 or more spans
    - inline_math as latex can be detected on span class
- **repo :zakir0101/pdf-element-extraction-kaggle** contain the server code currently in beta
- **class: advance_pdf_gui** handle the communication with server , [NOTE: later it will be moved to dedicated class or module]

### detectors/ocr_detectors :

- is responsible for parsing and  aggeregating the OCr output and save it in a structured form
- export it in html , where each element is heiglighted (see resources/question.css) , for seamless structure verfication 

---

## gui module:

- the main file "advance_pdf_gui" contain a simple yet powerfull tkinter App, which help with debugging all teh core component and previewing the results interactivly
- start it with python main.py test gui --group [latest,oldest,random..etc] --size [tiny,small,med..etc] [ --subjects 9709 9231 ..etc ]
- you can navigate selcted exams , render each page there , extract question and render them indevidually .. also highlight extracted part and subpart on the statusbar.
- you can ocr structured data and previews it on this Gui as renderd html page (rendered with pyright)  [see next section]
- **THIS CLASS WAS INITIALLY WRITTEN BY AI (JULES), BECAME RECENTLY VERY MESSY**, and include alot of not-well structured code , it should be refactored into logically independent cLasses/modules


---
---

# current pipline :

1. question extraction : parse pdfstream, iterated over pdf CMD , send each text-drawing command (TJ,Tj,T* ,..etc ) to the detector , which identify question/part/subpart , [ optionally pass each pdf CMD to BaseRendere for rendering the Page on cairo.ImageSurface as well, alternativly use the pymupdf for drawing the page into Png]
    - output of this stage is the question_list (of type models.question.Question)
    - entry point for this step is : engine.pdfEngine.extract_questions_from_pdf()
    - at the end of this step we also have drawen all pdf pages into PNG/Surface
- **for each question :**
2. crop the quesiton surface into a ImageSurface/PNG
3. futher crop each questionImage into sub-images for each part/subpart 
4. clean the number/label of the quesion/part from the image
5. send all the images for a single question to the OCRing server together .
6. parser the ocr result for that question and render it as html 
7. validate any detection errors 
8. move to next question 


---
---

# short-term goals :

### optimizing the pipline/workflow speed for rapid develpemnt, and keeping budget spent minimal :

**this require adjustment in 3 areas**

1. migrage to a cheap gpu-renting platform (vast.ai):
    - pick a decent gpu hosted in a datacenter with hight availabily and a somewhat good relayabilty 
    - rent a volumn (+30 Gb) in that datacenter for long-term (max 1 week, cost ~~ 1.00 $)
    - rent the device  for a short-period ( 30-60 min) only to download models,exams and virtual venv , save it all in the volumn , stop the instance directly ..
    - each time the local GUI start it should start/run the instance on the remote ( take few second ) , if not already running .
    - each time where long break will take place ( > 3 min) , immediatly stop the instance ... ( maybe automate this stopping process after in-activity )
    - if the GUi started but found the instance was deleted/destroyed for some reason (server was down,or has cleard cache), then Exit GUI , create a new intance on the device ( might take a while < 1 hour) .
    - repeat till done
    -

2. sever-side enhancment :
    - client should NOT send Image/PDF/BINARY data to server : write a downloader.py script , which can locate exam-pdfs on the web download them directly to the rented  datacenter VOLUMN ( part of the intial setup)
    - Batch-processing : as soon as GUI finish extracting_question for a specifc exam , send "ONLY" the quesitons_list to serverat once , process the whole question at once async , client should check status requrally through and endpoint and fetch result for a question of interrest .
    - implemtn cache : if a quesion_hash does not change in the new requeset use the old cached version. 
    -

3. **client-side enhancement** :
    - when detecting question, ovoid all unnessary work like in the EngineState and BaseRenderer, or loading fonts ..  
    **#TODO:** add new light-mode option which only parse pdf-page-stream and skipp all CMD except those needed by the detector [tj* , ctm , tm ,tm ,..etc] 
    - use a fast deticated module for the acutal rendering (like pymupdf, or like that "??" one with C-binding)
    - refactor/modularize the Tkinter APP (advance_pdf_gui) ...
    - make the pyright engine work efficiently :
        - start the moduel it only once
        - find faster alternative to screen_shot , which can directly map the output to tkinter tkImage 
        - use the UN-scaled dimenstion for viewport and scale all images down ..
    - 

4. finally :  
    ** after making sure the engine- and detector- modules are working accuratly, move them to the server side for faster proccessing, only keep the gui code to run locally 
