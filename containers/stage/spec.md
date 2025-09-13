# stage

## Scenario: stage files into a manifest
* When I run stage with an input directory and manifest path
* Then the manifest lists the staged files

## Scenario: verbose logging
* Given a file "<src>"
* And an output directory "<out>"
* When I pass --input "<src>"
* And I pass --dest-dir "<out>"
* And I pass --verbose
* And I run stage
* Then "created" is printed to stderr
