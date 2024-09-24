#!/usr/bin/env python3
#
# This script opens a given serial port and waits for data. When data is received, it is dumped
# to a file on disk byte by byte. The data in memory is flushed to disk after each byte to ensure
# that the timer thread does not prematurely consider the print job to be complete. The delay after
# which a job is finished can be set by adjusting TIMEOUT_S. Note that CTS/DTR and XON/XOF are not
# handled or addressed currently. When a job is considered complete, a binary (gpcl6 from the
# Ghostscript project is currently used) is called to convert the PCL datafile into a human
# readable format. While logic is in place for byte-by-byte parsing in order to detect discrete
# beginning and endings of jobs, these do not appear to exist, or come in the shape of out-of-band
# signalling on the serial line.
# PDF is the preferred conversion target, but PNG is available, too. Adjust the PCL_ARGS accordingly
# depending on the arguments used.
# To bypass the requirement of having a serial port, /dev/ttyACM0 or other (virtual) devices can be
# specified. This allows another process to write raw PCL to the buffer file in order for PCL dump
# to render it.
#
# ## Plus
#
# PCL dump + (plus) is an expansion on the original PCL dump utility, but featuring a GUI for mouse,
# touchscreen or hotkey input. While STDOUT and STDERR remain identical to PCL dump, plus focuses on
# presenting all typically useful output to the GUI, too. It allows (single page) PDF and PNG files
# to be previewed directly when received or from saved traces on disk. PDF is highly recommended.
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

# Plus requirements
import tkinter as tk                # GUI elements
from tkinter import ttk
from tkinter import messagebox as mb
from tkinter import scrolledtext
from tkinter.filedialog import askopenfilename
from PIL import Image, ImageTk      # image support
import fitz                         # PDF support

# config parameters
SERIAL_PORT = '/dev/ttyUSB0'                    # serial port to use
SERIAL_RATE = 19200                             # BAUD rate. HP 54645D goes up to 19200
SERIAL_IGNORE = False                           # bypass attaching to the serial interface
BUFFER_FILE = '/tmp/scope.dump'                 # data buffer file on disk
KEEP_BUFFER = False                             # keep the buffer (disk only), can be used for debugging or batch jobs
TIMEOUT_S = 2                                   # timeout before rendering job in seconds
PCL_BINARY = '/usr/local/bin/gpcl6'             # binary called to convert the PCL dump to another format
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

# global event for pausing/resuming capture
serialPause = Event()
version = '1.0'

root = tk.Tk()  # define root window in order to be able to create global StringVars
status_serial = tk.StringVar()
status_bytes = tk.StringVar()
status_last_capture = tk.StringVar()
# logger frame
if NATIVE_LOGGER == True:
    logger_frame = tk.Frame(root, width=850, height=300)
    text_area = scrolledtext.ScrolledText(logger_frame,
                                      wrap = tk.WORD,
                                      width = 71,
                                      height = 8,
                                      font = ("TkFixedFont", 11))
    text_area.config(background='black', foreground='#0F0')
    text_area.grid(column = 0, pady = 10, padx = 0)
    logger_frame.grid(row=1, column=0, columnspan=2)

# get the size of the dumpfile on disk
def getSize(fileobject):
    fileobject.seek(0,2) # move the cursor to the end of the file
    size = fileobject.tell()
    return size

# Timer task which monitors the file on disk
def timerRun(timer_runs):
    global serial_stop
    global status_serial
    global status_bytes
    while timer_runs.is_set():
        if not serialPause.is_set():
            status_serial.set('Serial input: RUNNING')
            readfile = open(BUFFER_FILE, 'rb')
            size_first_check = getSize(readfile)
            if size_first_check == 0:
                printConsole("Waiting for input.", newLine=False, animateDots=True)
                status_bytes.set('Not receiving data')
            time.sleep(TIMEOUT_S)
            size_last_check = getSize(readfile)
            if size_last_check != 0:
                # if it's the first byte, add a newline
                if size_first_check == 0:
                    printConsole("Starting job processing...", startNewLine=True)
                if size_last_check == size_first_check:
                    printConsole("Job complete, rendering...", startNewLine=True, newLine=False)
                    readfile.close()
                    renderFile()
                    clearBuffer()
                else:
                    printConsole("Receiving data (" + str(size_last_check) + " bytes).", newLine=False, animateDots=True)
                    status_bytes.set('Receiving data: (' + str(size_last_check) + ' bytes)')
        else:
            time.sleep(0.2) # without a delay in an empty loop the output tends to interfere with the next line
            status_serial.set('Serial input: STOPPED')
            printConsole("Capture paused, idle.", newLine=False, animateDots=True)

# render the file as a PDF
def renderFile():
    now = datetime.datetime.now()
    file_name = FILE_DIR + '/' + FILE_BASENAME + now.strftime("%Y-%m-%d_%H:%M:%S") + '.' + CONV_FORMAT
    render_command = PCL_BINARY + ' ' + PCL_ARGS + ' ' + file_name + ' ' + BUFFER_FILE
    # update GUI to reflect last capture moment
    global status_last_capture
    status_last_capture.set(str(now.strftime("%Y-%m-%d %H:%M:%S")))
    try:
        subprocess.check_output(render_command, shell=True)
    except subprocess.CalledProcessError as err:
        printConsole("ERROR: Failed to decode PCL using \"" + PCL_BINARY + "\" with error " + str(err) + "!", startNewLine=True, newLine=True)
    if CONV_FORMAT == 'png' and PNG_PHOSPHOR == True:
        printConsole("Phosphor PNG mode enabled, processing...", startNewLine=True)
        try:
            subprocess.run(PNG_PHOSPHOR_CMD + ' ' + file_name + ' ' + PNG_PHOSPHOR_ARGS + ' ' + file_name, shell=True)
        except OSError as err:
            printConsole("ERROR: Failed to run phosphor processing on file \"" + file_name + "\" with error " + str(err) + "!", startNewLine=True, newLine=True)
    if PREVIEW == True and not PREVIEW_NATIVE == True:
        printConsole("Rendered file, launching viewer...", startNewLine=True)
        try:
            subprocess.check_output(FILE_VIEWER + " " + file_name, shell=True)
        except subprocess.CalledProcessError as err:
            printConsole("WARNING: Failed to launch viewer \"" + FILE_VIEWER + "\" with error " + str(err) + "!", startNewLine=True, newLine=True)
    elif PREVIEW_NATIVE == True:
        if CONV_FORMAT == 'png':
            previewImage(file_name)
        elif CONV_FORMAT = 'pdf':
            previewPDF(file_name)
    else:
        printConsole("Preview disabled, proceeding...", startNewLine=True)

# clear the dump file on disk
def clearBuffer():
    if KEEP_BUFFER == True:
        return
    else:
        bufferfile = open(BUFFER_FILE, 'rb')
        if getSize(bufferfile):
            bufferfile.close()
            open(BUFFER_FILE, 'w').close()
            printConsole("Cleared buffer on disk")

# console output with or without newline and dots
def printConsole(text_string='', newLine=True, startNewLine=False, animateDots=False, logToGUI=True, GUIOnly=False):
    if OUTPUT_DATETIME == True:
        now = datetime.datetime.now()
        log_prefix = '[' + now.strftime("%Y-%m-%d %H:%M:%S") + '] '
        text_string = log_prefix + text_string
    if GUIOnly == True:
        if NATIVE_LOGGER == True:
            text_area.configure(state="normal")
            text_area.insert("end", "\n" + text_string.replace('\r','').replace('\n',''))
            text_area.see(tk.END)
            text_area.configure(state="disabled")
    else:
        # detect terminal width in order to reserve characters for blanking
        rows, columns = os.popen('stty size', 'r').read().split()
        justify_string = '{:<' + str(int(columns)-1) + '}'
        if startNewLine == True:
            text_string = '\r\n' + text_string
        if newLine == True:
            print(justify_string.format(text_string), flush=True, end='\r\n')
            if NATIVE_LOGGER == True and not logToGUI == False:
                text_area.configure(state="normal")
                text_area.insert("end", "\n" + text_string.replace('\r','').replace('\n',''))
                text_area.see(tk.END)
                text_area.configure(state="disabled")
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
                    text_area.configure(state="normal")
                    text_area.insert("end", "\n" + text_string.replace('\r','').replace('\n',''))
                    text_area.see(tk.END)
                    text_area.configure(state="disabled")

# determine keypress
def getCh():
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(sys.stdin.fileno())
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    return ch

# handle keyboard input
def handleInput():
    global serialPause
    while True:
        char = getCh()
        if (char.lower() == "q"):
            printConsole("'Q' received, exiting...", startNewLine=True)
            time.sleep(0.5)
            printConsole("Goodbye")
            os._exit(0)

        if (char.lower() == "p"):
            printConsole("'P' received, aborting capture...", startNewLine=True, logToGUI=False)
            startStopSerial(mode='stop')

        if (char.lower() == "r"):
            printConsole("'R' received, resuming serial capture...", startNewLine=True, logToGUI=False)
            startStopSerial(mode='start')

        if (char.lower() == "i"):
            displayParams()

        if (char.lower() == "h" or char == "F1"):
            displayHelp()

# start and stop serial input
def startStopSerial(mode=''):
    global serialPause
    if mode == 'start':
        clearBuffer()
        serialPause.clear()
        printConsole("'R' received, resuming serial capture...", GUIOnly=True)
    elif mode == 'stop':
        serialPause.set()
        printConsole("'P' received, aborting capture...", GUIOnly=True)

# handle command args
def handleArgs():
    global version
    parser = argparse.ArgumentParser(description="PCL dump")
    parser.add_argument('-n', help='Ignore serial port absence', action="store_true")
    parser.add_argument("-k", help="Keep buffer on disk", action="store_true")
    parser.add_argument('-v', '--version', help='Show version and exit', default=False, action='version', version=version)
    args = parser.parse_args()

    # set flags accordingly
    if args.n:
        global SERIAL_IGNORE
        SERIAL_IGNORE = True
    if args.k:
        global KEEP_BUFFER
        KEEP_BUFFER = True

# store serial input
def listenSerial(serialPause):
    if not SERIAL_IGNORE == True:
        try:
            ser = serial.Serial(SERIAL_PORT, SERIAL_RATE)
        except OSError as err:
            printConsole("Failed to open interface " + SERIAL_PORT + " with error " + str(err) + "!")
            printConsole("Unable to continue, exiting...")
            printConsole("Goodbye")
            os._exit(5)

        # open a file for writing
        try:
            dumpfile = open(BUFFER_FILE, "wb")
        except OSError as err:
            printConsole("Failed to open buffer file " + BUFFER_FILE + " with error " + str(err) + "!")
            printConsole("Unable to continue, exiting...")
            printConsole("Goodbye")
            os._exit(5)
        while True:
            if not serialPause.is_set():
                databyte = ser.read(1)
                #print(databyte)
                dumpfile.write(databyte)
                dumpfile.flush()
    else:
        printConsole("Skipping configured interface " + SERIAL_PORT + ". Serial input disabled.")

# show operating parameters
def displayParams():
    printConsole("Serial params:        " + SERIAL_PORT + " @ " + str(SERIAL_RATE) + " using a " + str(TIMEOUT_S) + "s timeout", startNewLine=True)
    if KEEP_BUFFER == True:
        buffer_persistence = " with persistence"
    else:
        buffer_persistence = " without persistence"
    printConsole("Buffer on disk:       " + BUFFER_FILE + buffer_persistence)
    printConsole("Render options:       " + CONV_FORMAT.upper() + " (using \"" + PCL_BINARY + "\" with \"" + PCL_ARGS + "\")")
    printConsole("File storage:         " + FILE_DIR + " (using \"" + FILE_BASENAME + "\" as the prefix)")
    printConsole("Preview:              " + str(PREVIEW) + " (using \"" + FILE_VIEWER + "\" to display files)")
    time.sleep(0.3)

# display help in CLI
def displayHelp():
    printConsole("Help:", startNewLine=True)
    printConsole("H or F1    [H]elp", startNewLine=True)
    printConsole("I          [I]nformation parameters")
    printConsole("P          [P]ause serial input")
    printConsole("R          [R]esume serial input")
    printConsole("Q          [Q]uit PCL dump")
    printConsole("")

# display utility version
def displayVersion():
    printConsole("HP PCL dump - version " + version, startNewLine=True)

# display help / about GUI dialog
def displayAbout():
    tk.Tk().withdraw()
    mb.showinfo(title="PCL dump + " + version, message="PCL dump + " + version, detail=\
        "The PCL dump + (plus) utility is intended to provide a simple " + \
        "frontend for the PCL dump service. Traces can be automatically " + \
        "previewed natively and the timestamp of the last trace is retained.\n" + \
        "PCL dump + also indicates the current status of the serial polling " + \
        "mechanism and the progress of any incoming job in bytes.\n"
        "\n\n" + \
        "Hotkeys:  \n" + \
        "          [t]oggle scale factor in trace window \n" + \
        "  [F2] or [p]ause the serial polling service \n" + \
        "  [F3] or [r]esume the serial polling service \n" + \
        "  [F1] or [h]help dialog (this screen) \n" + \
        " [F10] or [q]uit PCL dump + in main window \n")

# quit dialog for GUI
def quitApplication():
    tk.Tk().withdraw()
    res = mb.askquestion('Exit PCL dump +', 'Do you want to exit the program?')
    if res == 'yes' :
        os._exit(0)

# preview window for PNG
def previewImage(file='logo.png'):

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
    #window.bind('q', window.quit())

    image = Image.open(file)
    copy_of_image = image.copy()
    photo = ImageTk.PhotoImage(image)
    label = ttk.Label(window, image = photo)
    label.bind('<Configure>', resize_image)

    # display the file
    label.pack(fill='both', expand = 'YES')

# preview window for PDF
def previewPDF(file=''):
    page_num = 0
    # attempt to open file and get a matrix
    try:
        pdf = fitz.open(file)
        zoom = 1
        mat = fitz.Matrix(zoom, zoom)
    except:
        mb.showwarning(title="PCL dump + " + version, detail="Failed to open PDF file")
        #window.destroy()

    # generate an image from the PDF page
    def pdf_to_img(page_num):
        if mat:
            try:
                page = pdf.load_page(0)
                pix = page.get_pixmap(matrix=mat)
                return Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            except:
                mb.showwarning(title="PCL dump + " + version, detail="Failed to render PDF file",parent=window)
                #window.destroy()
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
            #mb.showwarning(title="PCL dump + " + version, detail="Failed to display PDF file")
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

# select a file and launch it in a new window
def openTrace():
    file = fileDialog(mode='OPEN', path=FILE_DIR)
    if file:
        if file.endswith('png'):
            previewImage(file)
        elif file.endswith('pdf'):
            previewPDF(file)

# display a file file dialog
def fileDialog(mode='OPEN', path=''):
    tk.Tk().withdraw() # we don't want a full GUI, so keep the root window from appearing
    if mode == 'OPEN':
        filename = askopenfilename(filetypes=[("Select trace", ".png .pdf")], initialdir=path)
    return filename

# main task launches the threads for the GUI, timer, input and serial listener
def main():
    root.title("PCL dump +")  # title of the GUI window
    root.resizable(0, 0)
    root.config(width=1000, height=600)
    #root.maxsize(900, 600)  # specify the max size the window can expand to
    root.config(bg="beige")  # specify background color
    root.protocol("WM_DELETE_WINDOW", lambda: quitApplication()) # catch close window action
    # hotkeys serial control
    root.bind('p', lambda event: startStopSerial('stop'))
    root.bind('P', lambda event: startStopSerial('stop'))
    root.bind("<F2>", lambda event: startStopSerial('stop'))
    root.bind('r', lambda event: startStopSerial('start'))
    root.bind('R', lambda event: startStopSerial('start'))
    root.bind("<F3>", lambda event: startStopSerial('start'))
    # hotkeys help
    root.bind('h', lambda event: displayAbout())
    root.bind('H', lambda event: displayAbout())
    root.bind("<F1>", lambda event: displayAbout())
    # hotkeys quit
    root.bind('q', lambda event: quitApplication())
    root.bind('Q', lambda event: quitApplication())
    root.bind("<F10>", lambda event: quitApplication())
    # hotkeys information
    root.bind('i', lambda event: displayParams())
    root.bind('I', lambda event: displayParams())

    # create left and right frames
    left_frame = tk.Frame(root, width=200, height=400, bg='grey')
    left_frame.grid(row=0, column=0, padx=10, pady=5)
    right_frame = tk.Frame(root, width=650, height=400, bg='grey')
    right_frame.grid(row=0, column=1, padx=10, pady=5)

    # create labels in left_frame
    tk.Label(left_frame, text="PCL dump + " + version).grid(row=0, column=0, padx=5, pady=5)

    # load image
    image_logo = Image.open('logo.png')
    image_logo = image_logo.resize((300,400), Image.BOX)
    tkimage_logo = ImageTk.PhotoImage(image_logo)
    tk.Label(right_frame, image=tkimage_logo, height=400, width=300).grid(row=0,column=0, padx=5, pady=5)

    # tool bar frame
    tool_bar = tk.Frame(left_frame, width=100, height=400)
    tool_bar.grid(row=2, column=0, padx=5, pady=5)
    tk.Label(tool_bar, text="Controls").grid(row=0, column=0, padx=5, pady=3, ipadx=5)  # ipadx is padding inside the Label widget

    # buttons
    tk.Button(tool_bar, text="Open capture", command=lambda: openTrace(), width=10).grid(row=1, column=0, padx=5, pady=4)
    tk.Button(tool_bar, text="Stop serial", command=lambda: startStopSerial(mode='stop'), width=10).grid(row=2, column=0, padx=5, pady=4)
    tk.Button(tool_bar, text="Start serial", command=lambda: startStopSerial(mode='start'), width=10).grid(row=3, column=0, padx=5, pady=4)
    tk.Button(tool_bar, text="Help / About", command=lambda: displayAbout(), width=10).grid(row=4, column=0, padx=5, pady=4)
    tk.Button(tool_bar, text="Quit", command=lambda: quitApplication(), width=10).grid(row=5, column=0, padx=5, pady=4)

    #status_window = tk.Label(tool_bar, text='', background='white', width=30, height=7).grid(row=6, column=0, padx=10, pady=10)
    label_status = tk.Label(tool_bar, textvariable=str(status_serial), width=25, height=1, background='black', foreground='#0F0', font=("TkFixedFont", 12)).grid(row=7, column=0, padx=10, pady=8)
    tk.Label(tool_bar, textvariable=status_bytes, width=25, height=1, background='black', foreground='#0F0', font=("TkFixedFont", 12)).grid(row=8, column=0, padx=10, pady=8)
    tk.Label(tool_bar, textvariable=status_last_capture, width=25, height=1, background='black', foreground='#0F0', font=("TkFixedFont", 12)).grid(row=9, column=0, padx=10, pady=8)
    status_last_capture.set('No captures in session')

    displayVersion()
    #time.sleep(0.5)
    # display config parameters and parse arguments
    handleArgs()
    displayParams()

    printConsole("Hotkeys: [P] to [p]ause capture, [R] to [r]esume capture, [I] to display [i]nformation, [Q] to [q]uit", startNewLine=True)
    printConsole("         Press [H] or [F1] for help")
    printConsole("Starting timer thread...", startNewLine=True)
    # timer for serial monitor
    timer_runs = Event()
    timer_runs.set()
    t = Thread(target=timerRun, args=(timer_runs,))
    t.start()

    # set up keyboard input handling
    printConsole("Starting keyboard input thread...")
    ki = Thread(target=handleInput)
    ki.start()

    # set up the serial listener thread
    printConsole("Starting serial listener thread...")
    sl = Thread(target=listenSerial, args=(serialPause,))
    sl.start()

    # run the GUI thread/loop
    printConsole("Launching GUI thread...")
    wl = Thread(target=root.mainloop())
    wl.start()
    os._exit(0)

if __name__ == "__main__":
    main()
