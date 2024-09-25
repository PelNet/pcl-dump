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
PNG_PHOSPHOR_ARGS = "-alpha off -fill \"#00EE00\" -draw 'color 0,0 replace' +level-colors green,black -auto-level"  # arguments for phosphor conversion
PREVIEW = True                                  # whether to automatically preview rendered files
COMMANDS_STARTUP = ['++srqauto 1\r\n', '++read\r\n', '++read\r\n']   # commands that are sent to the serial bus at startup
COMMANDS_DELAY = 1.2                            # delay between commands executed (sent) to the serial bus

# global event for pausing/resuming capture
serialPause = Event()
version = '1.0'

# get the size of the dumpfile on disk
def getSize(fileobject):
    fileobject.seek(0,2) # move the cursor to the end of the file
    size = fileobject.tell()
    return size

# Timer task which monitors the file on disk
def timerRun(timer_runs):
    global serial_stop
    while timer_runs.is_set():
        if not serialPause.is_set():
            readfile = open(BUFFER_FILE, 'rb')
            size_first_check = getSize(readfile)
            if size_first_check == 0:
                printConsole("Waiting for input.", newLine=False, animateDots=True)
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
        else:
            time.sleep(0.2) # without a delay in an empty loop the output tends to interfere with the next line
            printConsole("Capture paused, idle.", newLine=False, animateDots=True)

# render the file as a PDF
def renderFile():
    now = datetime.datetime.now()
    file_name = FILE_DIR + '/' + FILE_BASENAME + now.strftime("%Y-%m-%d_%H:%M:%S") + '.' + CONV_FORMAT
    render_command = PCL_BINARY + ' ' + PCL_ARGS + ' ' + file_name + ' ' + BUFFER_FILE
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
    if PREVIEW == True:
        printConsole("Rendered file, launching viewer...", startNewLine=True)
        try:
            subprocess.check_output(FILE_VIEWER + " " + file_name, shell=True)
        except subprocess.CalledProcessError as err:
            printConsole("WARNING: Failed to launch viewer \"" + FILE_VIEWER + "\" with error " + str(err) + "!", startNewLine=True, newLine=True)
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
def printConsole(text_string='', newLine=True, startNewLine=False, animateDots=False):
    rows, columns = os.popen('stty size', 'r').read().split()
    justify_string = '{:<' + str(int(columns)-1) + '}'
    if startNewLine == True:
        text_string = '\r\n' + text_string
    if newLine == True:
        print(justify_string.format(text_string), flush=True, end='\r\n')
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
            printConsole("'P' received, aborting capture...", startNewLine=True)
            serialPause.set()

        if (char.lower() == "r"):
            printConsole("'R' received, resuming serial capture...", startNewLine=True)
            clearBuffer()
            serialPause.clear()

        if (char.lower() == "i"):
            displayParams()

        if (char.lower() == "h" or char == "F1"):
            displayHelp()

# handle command args
def handleArgs():
    global version
    parser = argparse.ArgumentParser(description="PCL dump")
    parser.add_argument('-n', help='Ignore serial port absence', action="store_true")
    parser.add_argument('-k', help='Keep buffer on disk', action="store_true")
    parser.add_argument('-p', type=str, metavar='[/dev/ttyS0]', help="Override serial port", required=False)
    parser.add_argument('-s', type=int, metavar='[baud]', help="Override serial speed", required=False)
    parser.add_argument('-f', type=str, metavar='[/tmp/raw]', help="Override buffer file", required=False)
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
        SERIAL_PORT = args.port
    if args.s:
        global SERIAL_RATE
        SERIAL_RATE = args.speed
    if args.f:
        global BUFFER_FILE
        BUFFER_FILE = args.buffer

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

        # send optional startup commands to serial interface
        logger.printConsole("Executing any startup commands...")
        for command in COMMANDS_STARTUP:
            logger.printConsole("Sending startup command " + command.replace('\r', '').replace('\n', '') + "...")
            ser.write(command.encode())
            time.sleep(COMMANDS_DELAY)

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
    printConsole("P          [P]ause serial input")
    printConsole("R          [R]esume serial input")
    printConsole("Q          [Q]uit PCL dump")
    printConsole("")

# display utility version
def displayVersion():
    printConsole("HP PCL dump - version " + version, startNewLine=True)

# main task launches the threads for the timer, input and serial listener
def main():
    displayVersion()
    time.sleep(0.5)
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

if __name__ == "__main__":
    main()
