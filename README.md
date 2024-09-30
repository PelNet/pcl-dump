#  Scope Dump [plus|pro]

 This script opens a given serial port and waits for data. When data is received, it is dumped to a file on disk byte by byte. The data in memory is flushed to disk after each byte to ensure
 that the timer thread does not prematurely consider the print job to be complete. The delay after which a job is finished can be set by adjusting TIMEOUT_S. Note that CTS/DTR and XON/XOF are not
 handled or addressed currently. When a job is considered complete, a binary (gpcl6 from the Ghostscript project is currently used) is called to convert the PCL/HPGL datafile into a human
 readable format. While logic is in place for byte-by-byte parsing in order to detect discrete beginning and endings of jobs, these do not appear to exist, or come in the shape of out-of-band
 signalling on the serial line.

 ![Screenshot of Scope dump Pro in action](https://github.com/PelNet/pcl-dump/blob/916e82095b6e2bce3c606d685a1ff4a72f613091/traces/pcl_dump_pro.jpg)
 
 PDF is the preferred conversion target, but PNG is available, too. Adjust the PCL_ARGS accordingly depending on the arguments used.
 
 To bypass the requirement of having a serial port, /dev/ttyACM0 or other (virtual) devices can be specified. This allows another process to write raw PCL to the buffer file in order for Scope dump
 to render it. Alternatively, you can also use the `-n` argument to ignore the serial interface.

 If you need to run multiple instances of the utility, specify the serial port and buffer file individually using the command line arguments. This prevents conflicts.

 In some cases, a serial interface may require some initialization (such as when using the AR488 or similar). You can define any number of commands to be sent (blindly) to the serial port at startup
 with a specified delay between them. Often, these will need a linebreak appended to them, depending on the interface/device in question.

 ~~## Plus~~

 ~~PCL dump + (plus) is an expansion on the original PCL dump utility, but featuring a GUI for mouse, touchscreen or hotkey input. While STDOUT and STDERR remain identical to PCL dump, plus focuses on
 presenting all typically useful output to the GUI, too. It allows (single page) PDF and PNG files to be previewed directly when received or from saved traces on disk. PDF is highly recommended.~~

 ## Pro

 Scope dump Pro builds on the original Scope dump utility with the GUI and hotkeys from Scope dump plus. It features a modular, class based approach while remaining identical in functionality. This allows
 some minor improvements to the key bindings in preview windows and re-usage of the code if desired.


## TL;DR: 
 * scope_dump.py is a CLI only utility, plus and Pro have GUI's 
 * pcl_dump_plus.py is really just an intermediary step between the CLI only utility and Pro.
 * Skip "plus" and use scope_dump.py for CLI only or scope_dump_pro for a GUI.
 * This utility only *reads* the serial port, currently. No sending/reply is implemented except for the startup commands.
 * You do NOT need the Linux GPIB driver, just a serial port. 
 * Target device was an HP 54645D scope. It may work for others. You may need to adjust some defaults.
 * To run multiple instances simultaneously, use the command lines args for separate buffers and ports.


 If the scope or instrument in question does not have a serial interface but supports GPIB/HP-IB/IEEE488 you could take a look at the AR488, a simple GPIB adapter which requires only a common 
 microcontroller:

 https://github.com/Twilight-Logic/AR488

 So far this has been tested 'natively' using the HP 54652B on a 54645D scope using the serial interface, and with an AR488 (using GPIB) as the serial interface from an HP 54600A and a Tektronix
 2430. 

 ## Syntax

 `-n`                Disables the initialization of a serial port. This allows other applications to write raw PCL/HPGL to the buffer file in order for Scope dump to render it.
 
 `-k`                Prevents the buffer file from being flushed when a job has been processed. Used to keep the buffer for analysis or re-rendering the data to another format.
 
 `-p [port]`         Allows a serial port to be specified from the command line which is practical if you're switching between interfaces a lot or run multiple instances.
 
 `-s [baudrate]`     Allows the serial baud rate to be specified manually. Often used in combination with `-p`.
 
 `-f [file]`         Overrides the buffer file used by the utility. Often used in combination with `-p` when running multiple instances.

 `-o [dir]`          Overrides the configured output directory.
 
 `-v`                Prints the utility version and exits.
 
 `-h --help`         Displays the possible command line arguments and exits.
 

 ## Hotkeys (CLI)

`[H|h] or [F1]`      Show inline help/keys overview

`[P|p]`              Pauses serial input processing

`[R|r]`              Resumes serial input processing

`[I|i]`              Shows the main configured parameters

`[Q|q]`              Gracefully quits the utility


 ## Hotkeys (GUI, Scope dump Pro)

 ### Main window
`[H|h] or [F1]`      Show the About dialog with help/keys overview

`[I|i]`              Shows the main configured parameters

`[O|o] or [F11]`     Open stored trace(s) from disk. Multiple files can be selected

`[C|c] or [F12]`     Close all open trace windows

`[P|p] or [F2]`      Pauses serial input processing

`[R|r] or [F3]`      Resumes serial input processing

`[Q|q] or [F10]`     Gracefully quits the utility with a confirmation dialog


 ### Trace windows
 `[Q|q] or [Esc]`    Close the trace window in which the key was pressed
 
 `[T|t]`             Resizes the window and PNG or PDF to "original" size


 ## Config

 Many parameters are currently only configurable in the script(s). If you need a specific parameter to be specified from the command line, open an Issue and it will be addressed. 

| Parameter | Details |
| --- | --- |
| `SERIAL_PORT = '/dev/ttyACM1'` | Serial port to use, can be overridden with `-p` |
| `SERIAL_RATE = 115200` | BAUD rate used for the serial port, can be overridden with `-s` |
| `SERIAL_IGNORE = False` | bypass attaching to the serial interface, can be overridden to `True` by using `-n` |
| `BUFFER_FILE = '/tmp/scope.dump'` | data buffer file on disk, can be overridden with `-f` |
| `KEEP_BUFFER = False` | keep the buffer (disk only) for debugging or batch jobs, can be overridden by using `-k` |
| `TIMEOUT_S = 2` | timeout before rendering job in seconds. You may need to increase this timeout for devices that have gaps in their output |
| `PCL_BINARY = '/usr/local/bin/gpcl6'` | binary called to convert the PCL/HPGL dump to another format. Can also be `hp2xx` if you're receiving HPGL. `gpcl6` is part of the Ghostscript suite |
| `PCL_ARGS = '-sDEVICE=pdfwrite -o '` | optional arguments for above binary - use empty string for none |
| `FILE_DIR = os.environ['HOME']` | location to render the resulting files |
| `FILE_BASENAME = 'scope_output_'` | file name prefix for rendered files |
| `FILE_VIEWER = 'firefox'` | command used to preview the rendered files when using non-native previews in Scope dump Pro and is the only preview available in Scope dump |
| `CONV_FORMAT = 'pdf'` | file name suffix used for rendered files |
| `PNG_PHOSPHOR = True` | use ImageMagick to convert PNG files to a phoshor look. Technically this can be used for any post-processing on the PDF/image |
| `PNG_PHOSPHOR_CMD = '/usr/bin/convert'` | location of the ImageMagick binary for conversion. Any binary can be used |
| `PNG_PHOSPHOR_ARGS = "-alpha on -fill \"#00EE00\" -draw 'color 0,0 replace' +level-colors green,black -auto-level"` | arguments for phosphor conversion step |
| `PREVIEW = True` | whether to automatically preview rendered files when using Scope dump. Also used if `PREVIEW_NATIVE` is `False` in Scope dump Pro |
| `OUTPUT_DATETIME = True` | prefix output with a date and time stamp in log output (GUI and CLI) |
| `PREVIEW_NATIVE = True` | enable or disable GUI automatic previews using the native preview functionality of the utility (Scope dump Pro) |
| `PREVIEW_NATIVE_W = 544` | initial width to which to scale the image for native previewing |
| `PREVIEW_NATIVE_H = 704` | initial height to which to scale the image for native previewing |
| `NATIVE_LOGGER = True` | whether to show the native logger output in the GUI. If the logger is disabled, it will be hidden from the main window (Scope dump Pro) |
| `COMMANDS_STARTUP = ['++mode 0\r\n']` | commands that are sent to the serial bus at startup |
| `COMMANDS_DELAY = 1.2` | delay between commands executed (sent) to the serial bus in seconds at startup |
