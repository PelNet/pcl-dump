#  PCL Dump [plus|pro]

 This script opens a given serial port and waits for data. When data is received, it is dumped to a file on disk byte by byte. The data in memory is flushed to disk after each byte to ensure
 that the timer thread does not prematurely consider the print job to be complete. The delay after which a job is finished can be set by adjusting TIMEOUT_S. Note that CTS/DTR and XON/XOF are not
 handled or addressed currently. When a job is considered complete, a binary (gpcl6 from the Ghostscript project is currently used) is called to convert the PCL datafile into a human
 readable format. While logic is in place for byte-by-byte parsing in order to detect discrete beginning and endings of jobs, these do not appear to exist, or come in the shape of out-of-band
 signalling on the serial line.
 
 PDF is the preferred conversion target, but PNG is available, too. Adjust the PCL_ARGS accordingly depending on the arguments used.
 
 To bypass the requirement of having a serial port, /dev/ttyACM0 or other (virtual) devices can be specified. This allows another process to write raw PCL to the buffer file in order for PCL dump
 to render it. Alternatively, you can also use the `-n` argument to ignore the serial interface.

 If you need to run multiple instances of the utility, specify the serial port and buffer file individually using the command line arguments. This prevents conflicts.

 In some cases, a serial interface may require some initialization (such as when using the AR488 or similar). You can define any number of commands to be sent (blindly) to the serial port at startup
 with a specified delay between them. Often, these will need a linebreak appended to them, depending on the interface/device in question.

 ~~## Plus~~

 ~~PCL dump + (plus) is an expansion on the original PCL dump utility, but featuring a GUI for mouse, touchscreen or hotkey input. While STDOUT and STDERR remain identical to PCL dump, plus focuses on
 presenting all typically useful output to the GUI, too. It allows (single page) PDF and PNG files to be previewed directly when received or from saved traces on disk. PDF is highly recommended.~~

 ## Pro

 PCL dump Pro builds on the original PCL dump utility with the GUI and hotkeys from PCL dump plus. It features a modular, class based approach while remaining identical in functionality. This allows
 some minor improvements to the key bindings in preview windows and re-usage of the code if desired.


## TL;DR: 
 * pcl_dump.py is a CLI only utility, plus and Pro have GUI's 
 * pcl_dump_plus.py is really just an intermediary step between the CLI only utility and Pro.
 * Skip "plus" and use pcl_dump.py for CLI only or pcl_dump_pro for a GUI.
 * This utility only *reads* the serial port, currently. No sending/reply is implemented except for the startup commands.
 * You do NOT need the Linux GPIB driver, just a serial port. 
 * Target device was an HP 54645D scope. It may work for others. You may need to adjust some defaults.
 * To run multiple instances simultaneously, use the command lines args for separate buffers and ports.


 If the scope or instrument in question does not have a serial interface but support GPIB/HP-IB/IEEE488 you could take a look at the AR488, a simple GPIB adapter which requires only a common microcontroller:

 https://github.com/Twilight-Logic/AR488

 So far this has been tested 'natively' using the HP 54652B on a 54645D scope using the serial interface, and with an AR488 (using GPIB) as the serial interface from an HP 54600A and a Tektronix
 2430. 

 
