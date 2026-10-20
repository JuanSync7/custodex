# Run the fixture tool (tcl $argv switches: a switch -regexp block and a
# regexp character class).
foreach arg $argv {
    if {[regexp {^-[hq]} $arg]} {
        set quiet 1
    }
    switch -regexp -- $arg {
        ^-verbose {
            set verbose 1
        }
        ^-out-dir {
            set out_dir 1
        }
    }
}
