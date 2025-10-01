# guess_date

## Scenario: print the detected creation timestamp
* Given a media file "<media>"
* When I pass "<media>"
* And I run guess_date
* Then guess_date prints the creation timestamp

## Scenario: prefer interactive selection when scores tie
* Given multiple timestamps with similar confidence
* When I pass "<media>"
* And I run guess_date
* Then guess_date prompts me to choose a timestamp

## Scenario: fail when only filesystem mtime is available
* Given a media file "<media>"
* When I pass "<media>"
* And I pass "--fail-on-mtime-only"
* And I run guess_date
* Then guess_date exits with status 1
