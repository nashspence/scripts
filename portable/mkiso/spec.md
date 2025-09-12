# mkiso

## Scenario: build an ISO image
* Given a directory "<src>" containing files
* And an output directory "<out>"
* When I pass --src-dir "<src>"
* And I pass --out-dir "<out>"
* And I pass --out-file "<name>.iso"
* And I run mkiso
* Then mkiso writes the ISO to "<out>/<name>.iso"
* And mkiso prints "<name>.iso"

## Scenario: verbose logging
* Given a directory "<src>" containing files
* And an output directory "<out>"
* When I pass --src-dir "<src>"
* And I pass --out-dir "<out>"
* And I pass --out-file "<name>.iso"
* And I pass --verbose
* And I run mkiso
* Then mkiso writes the ISO to "<out>/<name>.iso"
* And mkiso prints "<name>.iso"
