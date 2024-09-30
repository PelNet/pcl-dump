#!/usr/bin/env python3
#
# This script opens a given serial port and waits for data. When data is received, it is dumped
# to a file on disk byte by byte. The data in memory is flushed to disk after each byte to ensure
# that the timer thread does not prematurely consider the print job to be complete. The delay after
# which a job is finished can be set by adjusting TIMEOUT_S. Note that CTS/DTR and XON/XOF are not
# handled or addressed currently. When a job is considered complete, a binary (gpcl6 from the
# Ghostscript project is currently used) is called to convert the PCL/HPGL datafile into a human
# readable format. While logic is in place for byte-by-byte parsing in order to detect discrete
# beginning and endings of jobs, these do not appear to exist, or come in the shape of out-of-band
# signalling on the serial line.
# PDF is the preferred conversion target, but PNG is available, too. Adjust the PCL_ARGS accordingly
# depending on the arguments used.
# To bypass the requirement of having a serial port, /dev/ttyACM0 or other (virtual) devices can be
# specified. This allows another process to write raw PCL to the buffer file in order for PCL dump
# to render it.
#
# ## Pro
#
# Scope dump Pro builds on the original PCL dump utility, but featuring a GUI for mouse,
# touchscreen or hotkey input. While STDOUT and STDERR remain identical to Scope dump, Pro focuses on
# presenting all typically useful output to the GUI, too. It allows (single page) PDF and PNG files
# to be previewed directly when received or from saved traces on disk. PDF is highly recommended.
# It features a modular, class based approach while remaining identical in functionality.
#
# PelliX 2024
#
import serial                       # serial input
import time
import datetime
import os
import argparse                     # optional arguments
from threading import Thread, Event # support for timer, input and serial threads
import subprocess                   # launch external commands
import sys, termios, tty            # keyboard input together with os and time

# Pro requirements
import tkinter as tk                # GUI elements
from tkinter import ttk
from tkinter import messagebox as mb
from tkinter import scrolledtext
from tkinter.filedialog import askopenfilename
from PIL import Image, ImageTk      # image support
import fitz                         # PDF support

# config parameters
SERIAL_PORT = '/dev/ttyACM1'                    # serial port to use
SERIAL_RATE = 115200                            # BAUD rate. HP 54645D goes up to 19200, AR488 is at 115200:q
SERIAL_IGNORE = False                           # bypass attaching to the serial interface
BUFFER_FILE = '/tmp/scope.dump'                 # data buffer file on disk
KEEP_BUFFER = False                             # keep the buffer (disk only), can be used for debugging or batch jobs
TIMEOUT_S = 2                                   # timeout before rendering job in seconds
PCL_BINARY = '/usr/local/bin/gpcl6'             # binary called to convert the PCL/HPGL dump to another format
PCL_ARGS = '-sDEVICE=pdfwrite -o '              # optional arguments for above binary - use empty string for none
#PCL_ARGS = '-sDEVICE=pngalpha -r128 -dGraphicsAlphaBits=4 -o '
FILE_DIR = os.environ['HOME']                   # location to render the resulting files
FILE_BASENAME = 'scope_output_'                 # file name prefix for rendered files
FILE_VIEWER = 'firefox'                         # command used to preview the rendered files
CONV_FORMAT = 'pdf'                             # file name suffix used for rendered files
PNG_PHOSPHOR = True                             # use ImageMagick to convert PNG files to a phoshor look
PNG_PHOSPHOR_CMD = '/usr/bin/convert'           # location of the ImageMagick binary for conversion
PNG_PHOSPHOR_ARGS = "-alpha on -fill \"#00EE00\" -draw 'color 0,0 replace' +level-colors green,black -auto-level"  # arguments for phosphor conversion
PREVIEW = True                                  # whether to automatically preview rendered files
OUTPUT_DATETIME = True                          # prefix output with a date and time stamp
PREVIEW_NATIVE = True                           # enable or disable GUI automatic previews
PREVIEW_NATIVE_W = 544                          # initial width to which to scale the image for native previewing
PREVIEW_NATIVE_H = 704                          # initial height to which to scale the image for native previewing
NATIVE_LOGGER = True                            # whether to show the native logger output in the GUI
COMMANDS_STARTUP = ['++srqauto 1\r\n', '++read\r\n', '++read\r\n']   # commands that are sent to the serial bus at startup
COMMANDS_DELAY = 1.2                            # delay between commands executed (sent) to the serial bus


# global events for pausing/resuming capture and closing trace windows
serialPause = Event()
eventCloseTraces = Event()
version = 'Pro 1.2'

### GUI class
class GUI(tk.Tk):

    def __init__(self, root):
        self.status_serial = tk.StringVar()
        self.status_bytes = tk.StringVar()
        self.status_last_capture = tk.StringVar()
        self.text_area = ''
        self.root = root

    # display the main GUI
    def mainWindow(self, root, input):
        self.input = input
        # logger frame
        if NATIVE_LOGGER == True:
            logger_frame = tk.Frame(root, width=850, height=300)
            self.text_area = scrolledtext.ScrolledText(logger_frame,
                                              wrap = tk.WORD,
                                              width = 71,
                                              height = 8,
                                              font = ("TkFixedFont", 11))
            self.text_area.config(background='black', foreground='#0F0')
            self.text_area.grid(column = 0, pady = 10, padx = 0)
            logger_frame.grid(row=1, column=0, columnspan=2)

        root.title("Scope dump " + version)  # title of the GUI window
        root.resizable(0, 0)
        root.config(width=1000, height=600)
        #root.maxsize(900, 600)  # specify the max size the window can expand to
        root.config(bg="beige")  # specify background color
        root.protocol("WM_DELETE_WINDOW", lambda: self.quitApplication()) # catch close window action

        # create left and right frames
        left_frame = tk.Frame(root, width=200, height=300, bg='grey')
        left_frame.grid(row=0, column=0, padx=10, pady=5)
        right_frame = tk.Frame(root, width=650, height=300, bg='grey')
        right_frame.grid(row=0, column=1, padx=10, pady=5)

        # create labels in left_frame
        tk.Label(left_frame, text="Scope dump " + version).grid(row=0, column=0, padx=5, pady=5)

        # load image
        image_logo = Image.open('logo.jpg')
        image_logo = image_logo.resize((300,300), Image.BOX)
        self.tkimage_logo = ImageTk.PhotoImage(image_logo) # use self to persist garbage collection
        tk.Label(right_frame, image=self.tkimage_logo, height=310, width=300).grid(row=0,column=0, padx=5, pady=5)

        # tool bar frame
        tool_bar = tk.Frame(left_frame, width=100, height=400)
        tool_bar.grid(row=2, column=0, padx=5, pady=5)
        tk.Label(tool_bar, text="Controls").grid(row=0, column=0, padx=5, pady=3, ipadx=5, columnspan=2)  # ipadx is padding inside the Label widget

        # buttons
        tk.Button(tool_bar, text="Open trace", command=lambda: self.openTrace(), width=10, underline=0).grid(row=1, column=0, padx=5, pady=4)
        tk.Button(tool_bar, text="Start capture", command=lambda: input.serialControl(command='start'), width=10, underline=3).grid(row=2, column=0, padx=5, pady=4)
        tk.Button(tool_bar, text="Help / About", command=lambda: self.displayAbout(), width=10, underline=0).grid(row=3, column=0, padx=5, pady=4)
        tk.Button(tool_bar, text="Quit", command=lambda: self.quitApplication(), width=10, underline=0).grid(row=3, column=1, padx=5, pady=4)
        tk.Button(tool_bar, text="Close traces", command=lambda: self.closeTraces(), width=10, underline=0).grid(row=1, column=1, padx=5, pady=4)
        tk.Button(tool_bar, text="Stop capture", command=lambda: input.serialControl(command='stop'), width=10, underline=3).grid(row=2, column=1, padx=5, pady=4)

        #status_window = tk.Label(tool_bar, text='', background='white', width=30, height=7).grid(row=6, column=0, padx=10, pady=10)
        label_status = tk.Label(tool_bar, textvariable=str(self.status_serial), width=25, height=1, background='black', foreground='#0F0', font=("TkFixedFont", 12)).grid(row=7, column=0, padx=10, pady=8, columnspan=2)
        tk.Label(tool_bar, textvariable=self.status_bytes, width=25, height=1, background='black', foreground='#0F0', font=("TkFixedFont", 12)).grid(row=8, column=0, padx=10, pady=8, columnspan=2)
        tk.Label(tool_bar, textvariable=self.status_last_capture, width=25, height=1, background='black', foreground='#0F0', font=("TkFixedFont", 12)).grid(row=9, column=0, padx=10, pady=8, columnspan=2)
        self.status_last_capture.set('No captures in session')
        self.status_serial.set('Loading...')
        self.status_bytes.set('Loading...')

        # hotkeys serial control
        root.bind('p', lambda event: input.serialControl(command='stop'))
        root.bind('P', lambda event: input.serialControl(command='stop'))
        root.bind("<F2>", lambda event: input.serialControl(command='stop'))
        root.bind('r', lambda event: input.serialControl(command='start'))
        root.bind('R', lambda event: input.serialControl(command='start'))
        root.bind("<F3>", lambda event: input.serialControl(command='start'))
        # hotkeys help
        root.bind('h', lambda event: self.displayAbout())
        root.bind('H', lambda event: self.displayAbout())
        root.bind("<F1>", lambda event: self.displayAbout())
        # open trace hotkeys
        root.bind('o', lambda event: self.openTrace())
        root.bind('O', lambda event: self.openTrace())
        root.bind("<F11>", lambda event: self.openTrace())
        # close traces hotkeys
        root.bind('c', lambda event: self.closeTraces())
        root.bind('C', lambda event: self.closeTraces())
        root.bind("<F12>", lambda event: self.closeTraces())
        # hotkeys quit
        root.bind('q', lambda event: self.quitApplication())
        root.bind('Q', lambda event: self.quitApplication())
        root.bind("<F10>", lambda event: self.quitApplication())
        # hotkeys information
        root.bind('i', lambda event: input.displayParams())
        root.bind('I', lambda event: input.displayParams())

        root.update_idletasks()

    # display help / about GUI dialog
    def displayAbout(self):
        tk.Tk().withdraw()
        mb.showinfo(title="Scope dump " + version, message="Scope dump " + version, detail=\
            "The Scope dump (plus) utility is intended to provide a simple " + \
            "frontend for the PCL/HPGL dump service. Traces can be automatically " + \
            "previewed natively and the timestamp of the last trace is retained.\n" + \
            "Scope dump also indicates the current status of the serial polling " + \
            "mechanism and the progress of any incoming job in bytes.\n"
            "\n\n" + \
            "Hotkeys:  \n" + \
            "          [t]oggle scale factor in trace window \n" + \
            "  [F2] or [p]ause the serial polling service \n" + \
            "  [F3] or [r]esume the serial polling service \n" + \
            "  [F1] or [h]help dialog (this screen) \n" + \
            " [F11] or [o]pen trace in main window \n" + \
            " [F12] or [c]lose all open trace windows \n" + \
            " [F10] or [q]uit PCL dump in main window \n")

    # quit dialog for GUI
    def quitApplication(self):
        tk.Tk().withdraw()
        res = mb.askquestion('Exit Scope dump', 'Do you want to exit the program?')
        if res == 'yes' :
            os._exit(0)

    # select a file and launch it in a new window
    def openTrace(self):
        files = self.fileDialog(mode='OPEN', path=FILE_DIR)
        if files:
            for file in files:
                preview = Trace()
                if file.endswith('png'):
                    preview.previewImage(file)
                elif file.endswith('pdf'):
                    preview.previewPDF(file)

    # close open trace windows
    def closeTraces(self):
        global eventCloseTraces
        eventCloseTraces.set()

    # display a file file dialog
    def fileDialog(self, mode='OPEN', path=''):
        tk.Tk().withdraw() # we don't want a full GUI, so keep the root window from appearing
        if mode == 'OPEN':
            selection = askopenfilename(filetypes=[("Select trace", ".png .pdf")], multiple=True, initialdir=path)
        return selection

    # print output in scrolledtext
    def logLine(self, text_string):
        self.text_area.configure(state="normal")
        self.text_area.insert("end", "\n" + text_string.replace('\r','').replace('\n',''))
        self.text_area.see(tk.END)
        self.text_area.configure(state="disabled")

    # wrapper to refresh the GUI
    def refresh(self):
        self.root.update_idletasks()

# serial handling
class SerialListener:

    def __init__(self, port, speed, bufferfile, logger):
        self.port = port
        self.speed = speed
        self.bufferfile = bufferfile
        self.logger = logger
        if not SERIAL_IGNORE == True:
            try:
                self.ser = serial.Serial(self.port, self.speed)
            except OSError as err:
                self.logger.printConsole("Failed to open interface " + self.port + " with error " + str(err) + "!", logToGUI=False)
                self.logger.printConsole("Unable to continue, exiting...", logToGUI=False)
                self.logger.printConsole("Goodbye", logToGUI=False)
                os._exit(5)
        #self.listenSerial(self, serialPause)

    # start and stop serial input
    def startStopSerial(self, mode=''):
        global serialPause
        if mode == 'start':
            self.clearBuffer()
            serialPause.clear()
            self.logger.printConsole("Resume received, resuming capture...", GUIOnly=True)
        elif mode == 'stop':
            serialPause.set()
            self.logger.printConsole("Pause received, aborting capture...", GUIOnly=True)

    # send message to serial bus
    def sendMessage(self, command=''):
        if not SERIAL_IGNORE == True:
            self.ser.write(command.encode())

    # store serial input
    def listenSerial(self, serialPause=Event()):
        if not SERIAL_IGNORE == True:
            # open a file for writing
            try:
                dumpfile = open(self.bufferfile, "wb")
            except OSError as err:
                self.logger.printConsole("Failed to open buffer file " + self.bufferfile + " with error " + str(err) + "!")
                self.logger.printConsole("Unable to continue, exiting...")
                self.logger.printConsole("Goodbye")
                os._exit(5)
            while True:
                if not serialPause.is_set():
                    databyte = self.ser.read(1)
                    #print(databyte)
                    dumpfile.write(databyte)
                    dumpfile.flush()
        else:
            self.logger.printConsole("Skipping configured interface " + self.port + ". Serial input disabled.")

    # get the size of the dumpfile on disk
    def getSize(self, fileobject):
        fileobject.seek(0,2) # move the cursor to the end of the file
        size = fileobject.tell()
        return size

    # Timer task which monitors the file on disk
    def timerRun(self, gui=''):
        self.gui = gui
        while True:
            if not serialPause.is_set():
                self.gui.status_serial.set('Capture input: RUNNING')
                readfile = open(self.bufferfile, 'rb')
                size_first_check = self.getSize(readfile)
                if size_first_check == 0:
                    self.logger.printConsole("Waiting for input.", newLine=False, animateDots=True)
                    self.gui.status_bytes.set('Not receiving data')
                time.sleep(TIMEOUT_S)
                size_last_check = self.getSize(readfile)
                if size_last_check != 0:
                    # if it's the first byte, add a newline
                    if size_first_check == 0:
                        self.logger.printConsole("Starting job processing...", startNewLine=True)
                    if size_last_check == size_first_check:
                        self.logger.printConsole("Job complete, rendering...", startNewLine=True, newLine=True)
                        readfile.close()
                        trace = Trace()
                        trace.renderFile(self.gui, self.logger)
                        self.clearBuffer()
                    else:
                        self.logger.printConsole("Receiving data (" + str(size_last_check) + " bytes).", newLine=False, animateDots=True)
                        self.gui.status_bytes.set('Receiving data: (' + str(size_last_check) + ' bytes)')
            else:
                time.sleep(0.2) # without a delay in an empty loop the output tends to interfere with the next line
                self.gui.status_serial.set('Capture input: STOPPED')
                self.logger.printConsole("Capture paused, idle.", newLine=False, animateDots=True)

    # clear the dump file on disk
    def clearBuffer(self):
        if KEEP_BUFFER == True:
            return
        else:
            bufferfile = open(self.bufferfile, 'rb')
            if self.getSize(bufferfile):
                bufferfile.close()
                open(self.bufferfile, 'w').close()
                self.logger.printConsole("Cleared buffer on disk")

# traces
class Trace():

    # render the file as a PDF or PNG
    def renderFile(self, gui, logger):
        self.gui = gui
        self.logger = logger
        now = datetime.datetime.now()
        file_name = FILE_DIR + '/' + FILE_BASENAME + now.strftime("%Y-%m-%d_%H:%M:%S") + '.' + CONV_FORMAT
        render_command = PCL_BINARY + ' ' + PCL_ARGS + ' ' + file_name + ' ' + BUFFER_FILE
        # update GUI to reflect last capture moment
        self.gui.status_last_capture.set(str(now.strftime("%Y-%m-%d %H:%M:%S")))
        try:
            subprocess.check_output(render_command, shell=True)
        except subprocess.CalledProcessError as err:
            self.logger.printConsole("ERROR: Failed to decode data using \"" + PCL_BINARY + "\" with error " + str(err) + "!", startNewLine=True)
        if CONV_FORMAT == 'png' and PNG_PHOSPHOR == True:
            self.logger.printConsole("Phosphor PNG mode enabled, processing...", startNewLine=True)
            try:
                subprocess.run(PNG_PHOSPHOR_CMD + ' ' + file_name + ' ' + PNG_PHOSPHOR_ARGS + ' ' + file_name, shell=True)
            except OSError as err:
                self.logger.printConsole("ERROR: Failed to run phosphor processing on file \"" + file_name + "\" with error " + str(err) + "!", startNewLine=True)
        if PREVIEW == True and not PREVIEW_NATIVE == True:
            self.logger.printConsole("Rendered file, launching viewer...", startNewLine=True)
            try:
                subprocess.check_output(FILE_VIEWER + " " + file_name, shell=True)
            except subprocess.CalledProcessError as err:
                self.logger.printConsole("WARNING: Failed to launch viewer \"" + FILE_VIEWER + "\" with error " + str(err) + "!", startNewLine=True)
        elif PREVIEW_NATIVE == True:
            if CONV_FORMAT == 'png':
                self.previewImage(file_name)
            elif CONV_FORMAT == 'pdf':
                self.previewPDF(file_name)
        else:
            self.logger.printConsole("Preview disabled, proceeding...", startNewLine=True)

    # preview window for PNG
    def previewImage(self, file='logo.png'):

        # dynamically resize (a copy of) the image
        def resize_image(event):
            new_width = event.width
            new_height = event.height
            image = copy_of_image.resize((new_width, new_height), Image.ANTIALIAS)
            photo = ImageTk.PhotoImage(image)
            label.config(image = photo)
            label.image = photo #avoid garbage collection

        # zoom to original size
        def rescale_image(event):
            # to return to "normal" scaled mode, we look at the window geometry which is 2px larger
            # than the size we set it to before. If the image is scaled 100% or the window has been
            # resized from the default scale factor, we return to that. Normal scaled mode is 50% or 544x704.
            if (window.winfo_reqwidth() == image.width and window.winfo_reqheight() == image.height or
                window.winfo_reqwidth() != (PREVIEW_NATIVE_W+2) and window.winfo_reqheight() != (PREVIEW_NATIVE_H+2)):
                intended_width = PREVIEW_NATIVE_W
                intended_height = PREVIEW_NATIVE_H
            else:
                # work out the ratio of the image, adjust height accordingly as it's generally the
                # constraining factor and calculate the width from there
                img_width = image.width
                img_height = image.height
                img_ratio = image.width / image.height
                intended_height = (window.winfo_screenheight() -50) # subtract some overhead for toolbars
                intended_width = (intended_height * img_ratio)
            window.geometry(str(round(intended_width)) + "x" + str(intended_height))

        # spawn new window
        window = tk.Toplevel()
        window.title("Trace: " + file)
        window.geometry(str(PREVIEW_NATIVE_W) + "x" + str(PREVIEW_NATIVE_H))
        window.configure(background="black")
        window.bind('t', rescale_image)
        window.bind('T', rescale_image)
        window.bind('q', lambda event: window.destroy())
        window.bind('Q', lambda event: window.destroy())
        window.bind('<Escape>', lambda event: window.destroy())

        image = Image.open(file)
        copy_of_image = image.copy()
        photo = ImageTk.PhotoImage(image)
        label = ttk.Label(window, image = photo)
        label.bind('<Configure>', resize_image)

        # display the file
        label.pack(fill='both', expand = 'YES')

        # launch event handler for mass close in a thread
        self.window = window
        he = Thread(target=self.handleEvents)
        he.start()

    # preview window for PDF
    def previewPDF(self, file=''):
        page_num = 0
        # attempt to open file and get a matrix
        try:
            pdf = fitz.open(file)
            zoom = 1
            mat = fitz.Matrix(zoom, zoom)
        except:
            mb.showwarning(title="Scope dump " + version, detail="Failed to open PDF file")

        # generate an image from the PDF page
        def pdf_to_img(page_num):
            if mat:
                try:
                    page = pdf.load_page(0)
                    pix = page.get_pixmap(matrix=mat)
                    return Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                except:
                    mb.showwarning(title="Scope dump " + version, detail="Failed to render PDF file",parent=window)
            else:
                pass

        # display the image of the PDF
        def show_image(event=False):
            try:
                im = pdf_to_img(page_num)
                img_tk = ImageTk.PhotoImage(im)
                #panel = tk.Label(frame, image=img_tk)
                panel.config(image=img_tk)
                panel.pack(side="bottom", fill="both", expand="yes")
                frame.image = img_tk
                canvas.create_window(0, 0, anchor='nw', window=frame)
                frame.update_idletasks()
                canvas.config(scrollregion=canvas.bbox("all"))
            except:
                #mb.showwarning(title="PCL dump " + version, detail="Failed to display PDF file")
                window.destroy()

        # resize the image by regenerating it
        def resize_image(event):
            new_width = event.width
            new_height = event.height
            im = pdf_to_img(page_num)
            im_scaled = im.resize((new_width, new_height), Image.ANTIALIAS)
            img_tk = ImageTk.PhotoImage(im_scaled)
            panel.config(image=img_tk)
            panel.pack(side="bottom", fill="both", expand="yes")
            frame.image = img_tk
            frame.update_idletasks()

        # (re)turn document to 100% zoom factor
        def orig_size(event):
            im = pdf_to_img(page_num)
            img_tk = ImageTk.PhotoImage(im)
            panel.config(image=img_tk)
            panel.pack(side="bottom", fill="both", expand="yes")
            #window.geometry()
            frame.image = img_tk
            frame.update_idletasks()

        # spawn new window
        window = tk.Toplevel()
        window.title("Trace: " + file)
        # 45 pixels overhead for the scrollbar on the right
        window.geometry(str(PREVIEW_NATIVE_W + 45) + "x" + str(PREVIEW_NATIVE_H))
        window.configure(background="black")
        window.bind('t', orig_size)
        window.bind('T', orig_size)
        window.bind('q', lambda event: window.destroy())
        window.bind('Q', lambda event: window.destroy())
        window.bind('<Escape>', lambda event: window.destroy())

        # add scroll bar
        scrollbar = tk.Scrollbar(window)
        scrollbar.pack(side='right', fill='y')

        # add canvas
        canvas = tk.Canvas(window, yscrollcommand=scrollbar.set)
        canvas.pack(side='left', fill='both', expand=1)
        frame = tk.Frame(canvas)
        panel = tk.Label(frame)
        scrollbar.config(command = canvas.yview)
        canvas.bind("<Configure>", resize_image)
        # render the PDF
        show_image()
        #pdf.close() # don't close the PDF handle as we need it for resizing

        # launch event handler for mass close in a thread
        self.window = window
        he = Thread(target=self.handleEvents)
        he.start()

    # handle events for closing
    def handleEvents(self):
        while True:
            time.sleep(0.5) # back off to prevent hogging a CPU core
            global eventCloseTraces
            if eventCloseTraces.is_set():
                self.window.destroy()
                time.sleep(1) # give the trace window threads time to pick up the event
                eventCloseTraces.clear()

# logging
class Logger:

    def __init__(self, gui='', timestamps=False):
        self.timestamps = timestamps
        self.gui = gui

    # console output with or without newline and dots
    def printConsole(self, text_string='', newLine=True, startNewLine=False, animateDots=False, logToGUI=True, GUIOnly=False):
        loggui = self.gui
        if self.timestamps == True:
            now = datetime.datetime.now()
            log_prefix = '[' + now.strftime("%Y-%m-%d %H:%M:%S") + '] '
            text_string = log_prefix + text_string
        if GUIOnly == True:
            if NATIVE_LOGGER == True:
                loggui.logLine(text_string)
        else:
            # detect terminal width in order to reserve characters for blanking
            rows, columns = os.popen('stty size', 'r').read().split()
            justify_string = '{:<' + str(int(columns)-1) + '}'
            if startNewLine == True:
                text_string = '\r\n' + text_string
            if newLine == True:
                print(justify_string.format(text_string), flush=True, end='\r\n')
                if NATIVE_LOGGER == True and not logToGUI == False:
                    loggui.logLine(text_string)
            else:
                if animateDots == True:
                    # clear the line before printing on it again
                    blank_string = ''
                    i = 0
                    while i < int(columns):
                        blank_string += ' '
                        i += 1
                    print(justify_string.format(blank_string), end='\r')
                    now = datetime.datetime.now()
                    seconds = int(now.strftime("%S")[-1:])
                    dots = '.'
                    i = 1
                    while i < seconds:
                        dots += '.'
                        i += 1
                    print(justify_string.format(text_string + dots), end='\r', flush=True)
                else:
                    print(justify_string.format(text_string), end='\r', flush=True)
                    if NATIVE_LOGGER == True and not logToGUI == False:
                        loggui.logLine(text_string)
        # update the window anyway
        self.gui.refresh()

# input handling
class Input(Logger, SerialListener):

    def __init__(self, Logger, SerialListener):
        self.logger = Logger
        self.seriallistener = SerialListener

    # determine keypress
    def getCh(self):
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(sys.stdin.fileno())
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        return ch

    # handle keyboard input
    def handleInput(self):
        global serialPause
        while True:
            char = self.getCh()
            if (char.lower() == "q"):
                self.logger.printConsole("Quit signal received, exiting...", startNewLine=True)
                time.sleep(0.5)
                self.logger.printConsole("Goodbye")
                os._exit(0)

            if (char.lower() == "p"):
                self.logger.printConsole("Pause received, aborting capture...", startNewLine=True, logToGUI=False)
                self.seriallistener.startStopSerial(mode='stop')

            if (char.lower() == "r"):
                self.logger.printConsole("Resume received, resuming serial capture...", startNewLine=True, logToGUI=False)
                self.seriallistener.startStopSerial(mode='start')

            if (char.lower() == "i"):
                self.displayParams()

            if (char.lower() == "h" or char == "F1"):
                self.displayHelp()

    # handle GUI input
    def serialControl(self, command):
        if (command == 'stop'):
            self.seriallistener.startStopSerial(mode='stop')
        elif (command == 'start'):
            self.seriallistener.startStopSerial(mode='start')

    # show operating parameters
    def displayParams(self):
        self.logger.printConsole("Serial params:        " + SERIAL_PORT + " @ " + str(SERIAL_RATE) + " using a " + str(TIMEOUT_S) + "s timeout", startNewLine=True)
        if KEEP_BUFFER == True:
            buffer_persistence = " with persistence"
        else:
            buffer_persistence = " without persistence"
        self.logger.printConsole("Buffer on disk:       " + BUFFER_FILE + buffer_persistence)
        self.logger.printConsole("Render options:       " + CONV_FORMAT.upper() + " (using \"" + PCL_BINARY + "\" with \"" + PCL_ARGS + "\")")
        self.logger.printConsole("File storage:         " + FILE_DIR + " (using \"" + FILE_BASENAME + "\" as the prefix)")
        self.logger.printConsole("Preview:              " + str(PREVIEW) + " (using \"" + FILE_VIEWER + "\" to display files)")
        time.sleep(0.3)

    # display help in CLI
    def displayHelp(self):
        self.logger.printConsole("Help:", startNewLine=True)
        self.logger.printConsole("H or F1    [H]elp", startNewLine=True)
        self.logger.printConsole("I          [I]nformation parameters")
        self.logger.printConsole("P          [P]ause serial input")
        self.logger.printConsole("R          [R]esume serial input")
        self.logger.printConsole("Q          [Q]uit PCL dump")
        self.logger.printConsole("")

    # display utility version
    def displayVersion(self):
        self.logger.printConsole("Scope dump - version " + version, startNewLine=True)
        return

class ArgHandler:

    # handle command args
    def handleArgs(event):
        global version
        parser = argparse.ArgumentParser(description="Scope dump")
        parser.add_argument('-n', help='Ignore serial port absence', action="store_true")
        parser.add_argument('-k', help='Keep buffer on disk', action="store_true")
        parser.add_argument('-p', type=str, metavar='[/dev/ttyS0]', help="Override serial port", required=False)
        parser.add_argument('-s', type=int, metavar='[baud]', help="Override serial speed", required=False)
        parser.add_argument('-f', type=str, metavar='[/tmp/raw]', help="Override buffer file", required=False)
        parser.add_argument('-o', type=str, metavar='[/tmp/tek2]', help="Override output directory", required=False)
        parser.add_argument('-v', '--version', help='Show version and exit', default=False, action='version', version=version)
        args = parser.parse_args()

        # set flags accordingly
        if args.n:
            global SERIAL_IGNORE
            SERIAL_IGNORE = True
        if args.k:
            global KEEP_BUFFER
            KEEP_BUFFER = True
        if args.p:
            global SERIAL_PORT
            SERIAL_PORT = args.p
        if args.s:
            global SERIAL_RATE
            SERIAL_RATE = args.s
        if args.f:
            global BUFFER_FILE
            BUFFER_FILE = args.f
        if args.o:
            global FILE_DIR
            FILE_DIR = args.o

# main task launches the threads for the GUI, timer, input and serial listener
def main():
    root = tk.Tk()  # define root window in order to be able to create global StringVars
    args = ArgHandler()
    args.handleArgs()
    main_gui = GUI(root)
    logger = Logger(gui=main_gui, timestamps=OUTPUT_DATETIME)
    serial = SerialListener(port=SERIAL_PORT, speed=SERIAL_RATE, bufferfile=BUFFER_FILE, logger=logger)
    input = Input(logger, serial)
    main_gui.mainWindow(root, input)
    input.displayVersion()

    # display config
    input.displayParams()

    logger.printConsole("Hotkeys: [P] to [p]ause capture, [R] to [r]esume capture, [I] to display [i]nformation, [Q] to [q]uit", startNewLine=True)
    logger.printConsole("         Press [H] or [F1] for help")

    # send optional startup commands to serial interface
    if not SERIAL_IGNORE == True:
        logger.printConsole("Executing any startup commands...")
        for command in COMMANDS_STARTUP:
            time.sleep(COMMANDS_DELAY)
            logger.printConsole("Sending startup command " + command.replace('\r', '').replace('\n', '') + "...")
            serial.sendMessage(command=command)

    # timer for serial monitor
    logger.printConsole("Starting timer thread...", startNewLine=True)
    t = Thread(target=serial.timerRun, args=(main_gui,))
    t.start()

    # set up keyboard input handling
    logger.printConsole("Starting keyboard input thread...")
    ki = Thread(target=input.handleInput)
    ki.start()

    # set up the serial listener thread
    logger.printConsole("Starting serial listener thread...")
    sl = Thread(target=serial.listenSerial, args=(serialPause,)) # do not forget the trailing comma
    sl.start()

    # run the GUI thread/loop
    logger.printConsole("Launching GUI thread...")
    wl = Thread(target=root.mainloop())
    wl.start()

    os._exit(0)

if __name__ == "__main__":
    main()
