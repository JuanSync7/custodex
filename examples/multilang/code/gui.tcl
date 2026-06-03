# greet-gui: a tiny Tk front end for the greeter (the subject: tcl switches).
foreach arg $argv {
  if {[regexp {^\-+[tT]} $arg]} { set title $arg }
  if {[regexp {^\-+[gG]} $arg]} { set geometry $arg }
  if {[regexp {^\-+[qQ]} $arg]} { set quiet 1 }
}
