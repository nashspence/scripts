# posix-pipeline

## Scenario: record job completion with mark
* Given a workspace "<dir>"
* When I source posix-pipeline.sh
* And I run mark done "<dir>/job.marker"
* Then a file "<dir>/job.marker" exists
* And the file permissions are owner-only

## Scenario: skip work using mark check
* Given a workspace "<dir>"
* And a file "<dir>/job.marker" already exists
* When I source posix-pipeline.sh
* And I run mark check "<dir>/job.marker"
* Then the command exits with status 1

## Scenario: propagate failures in non-interactive shells
* Given a command "<cmd>" that exits with status 42
* When I source posix-pipeline.sh
* And I run retry "<cmd>" with stdin redirected from /dev/null
* Then the command exits with status 42
* And no retry prompt is printed
