# qcut

## Scenario: assemble highlight reel from a directory
* Given a directory "<src>" containing source videos
* And an output directory "<out>"
* When I pass --src-dir "<src>"
* And I pass --autoedit-dir "<out>"
* And I pass --target "<seconds>"
* And I pass --min "<min>"
* And I pass --max "<max>"
* And I pass --svt-preset "<preset>"
* And I pass --svt-crf "<crf>"
* And I pass --svt-lp "<lp>"
* And I pass --opus-br "<bitrate>"
* And I pass --fontfile "<font>"
* And I run qcut
* Then qcut encodes Matroska clips into "<out>"
* And qcut appends the clips with mkvmerge
* And ".job.json" in "<out>" records each clip
* And the final output uses the SVT-AV1 lp "<lp>"

## Scenario: skip already completed highlight reel
* Given a directory "<src>" containing source videos
* And an output directory "<out>"
* And a manifest in "<out>" whose "final" status is "done"
* And the manifest references a finished video in "<out>"
* When I pass --src-dir "<src>"
* And I pass --autoedit-dir "<out>"
* And I run qcut
* Then qcut prints the existing output file name
* And qcut exits without re-encoding clips

## Scenario: resume probes and clip encodes
* Given a directory "<src>" containing source videos
* And an output directory "<out>"
* And a manifest in "<out>" with partial probe results
* When I pass --src-dir "<src>"
* And I pass --autoedit-dir "<out>"
* And I run qcut
* Then qcut reuses probe durations from the manifest
* And qcut continues encoding remaining clips
* And the manifest records updated timestamps

## Scenario: enable verbose debug logging
* Given a directory "<src>" containing source videos
* And an output directory "<out>"
* When I pass --src-dir "<src>"
* And I pass --autoedit-dir "<out>"
* And I pass --debug-cmds
* And I pass --verbose
* And I run qcut
* Then qcut prints ffmpeg and ffprobe commands
* And qcut prints mkvmerge commands
