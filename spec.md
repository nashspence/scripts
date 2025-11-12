# padimg

## Scenario: pad an image to a taller aspect ratio
* Given an RGB image "<src>"
* And a desired output file "<dest>"
* When I pass "<src>"
* And I pass "<dest>"
* And I pass --ratio "4:5"
* And I run padimg
* Then padimg saves "<dest>"
* And the canvas height matches a 4:5 aspect ratio

## Scenario: pad an image to a wider aspect ratio
* Given a PNG with alpha "<src>"
* And no explicit output path
* When I pass "<src>"
* And I pass --ratio "3:2"
* And I pass --gray "64"
* And I run padimg
* Then padimg saves a file ending with "_padded.png"
* And transparent pixels are filled with gray level "64"
