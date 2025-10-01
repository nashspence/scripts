# guess_date

## Scenario: flatten files into timestamped names
* Given a directory "input/photos"
* And the file "input/photos/image.jpg" has modification time "2024-01-02T03:04:05"
* And an empty directory "output"
* When I set the command argument "input"
* And I set the command argument "output"
* And I run guess_date
* Then the directory "output" contains a file named "2024-01-02T03-04-05 photos__image.jpg"

## Scenario: send undated files to the unknown directory
* Given a directory "input"
* And the file "input/clip.mov" has no detectable timestamp metadata
* And an empty directory "output"
* When I set the command argument "input"
* And I set the command argument "output"
* And I run guess_date
* Then the directory "output/unknown" contains a file named "clip.mov"
