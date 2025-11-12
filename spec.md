# when

## Scenario: print the detected creation timestamp
* Given a media file "<media>"
* When I pass "<media>"
* And I run when
* Then when prints the creation timestamp

## Scenario: prefer interactive selection when scores tie
* Given multiple timestamps with similar confidence
* When I pass "<media>"
* And I run when
* Then when prompts me to choose a timestamp

## Scenario: fail when only filesystem mtime is available
* Given a media file "<media>"
* When I pass "<media>"
* And I pass "--fail-on-mtime-only"
* And I run when
* Then when exits with status 1
