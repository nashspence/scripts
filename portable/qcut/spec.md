# qcut

## Scenario: auto-edit a directory of videos
* Given a directory "<src>" containing videos
* And an output directory "<out>"
* When I pass --src-dir "<src>"
* And I pass --autoedit-dir "<out>"
* And I run qcut
* Then qcut writes the final video to "<out>"
* And the final video shows timestamp overlays

## Scenario: enable verbose logging
* Given a directory "<src>" containing videos
* And an output directory "<out>"
* When I pass --src-dir "<src>"
* And I pass --autoedit-dir "<out>"
* And I pass --verbose
* And I run qcut
* Then qcut writes the final video to "<out>"
