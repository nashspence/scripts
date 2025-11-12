# fitdisk

## Scenario: bundle files into target sized directories
* Given an input directory "<src>" containing files "<files>"
* And an empty output directory "<out>"
* When I pass --input-dir "<src>"
* And I pass --output-dir "<out>"
* And I pass --target-size "<size>"
* And I run fitdisk
* Then fitdisk creates numbered directories in "<out>"
* And each directory is no larger than "<size>"
* And every file from "<src>" appears in exactly one directory in "<out>"

## Scenario: move files instead of copying
* Given an input directory "<src>" containing files "<files>"
* And an empty output directory "<out>"
* When I pass --input-dir "<src>"
* And I pass --output-dir "<out>"
* And I pass --target-size "<size>"
* And I pass --move
* And I run fitdisk
* Then "<src>" no longer contains "<files>"
* And "<out>" contains the files grouped into numbered directories
