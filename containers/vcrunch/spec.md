# vcrunch

## Scenario: encode with custom parameters
* Given an MP4 file "<src>"
* And an output directory "<out>"
* When I pass --input "<src>"
* And I pass --target-size "<size>"
* And I pass --audio-bitrate "<audio>"
* And I pass --safety-overhead "<overhead>"
* And I pass --output-dir "<out>"
* And I pass --manifest-name "<manifest>"
* And I pass --name-suffix "<suffix>"
* And I pass --svt-lp "<lp>"
* And I run vcrunch
* Then vcrunch creates an AV1 file in "<out>"
* And the file name ends with "<suffix>.mkv"
* And "<manifest>" records "<src>" as done
* And the encode respects the target size
* And the encode respects the audio bitrate
* And the encode respects the safety overhead
* And the encode uses the SVT-AV1 lp "<lp>"

## Scenario: skip already encoded videos
* Given an MP4 file "<src>"
* And "<src>" already encoded into "<out>" with name ending "<suffix>.mkv"
* And a manifest "<manifest>" in "<out>" marking "<src>" as done
* When I pass --input "<src>"
* And I pass --output-dir "<out>"
* And I pass --manifest-name "<manifest>"
* And I pass --name-suffix "<suffix>"
* And I run vcrunch
* Then vcrunch skips "<src>"

## Scenario: read inputs from a list and filter by glob
* Given a list file "<list>" containing paths
* And some paths match "<pattern>" and others do not
* When I pass --paths-from "<list>"
* And I pass --pattern "<pattern>"
* And I run vcrunch
* Then matching video files are transcoded
* And non-matching paths are skipped

## Scenario: copy files when inputs fit target size
* Given an MP4 file "<src>"
* And an output directory "<out>"
* When I pass --input "<src>"
* And I pass --target-size "<size>"
* And I pass --output-dir "<out>"
* And I run vcrunch
* Then "<src>" is copied to "<out>"
* And ".job.json" records "<src>" as done

## Scenario: move files when inputs fit target size
* Given an MP4 file "<src>"
* And an output directory "<out>"
* When I pass --input "<src>"
* And I pass --target-size "<size>"
* And I pass --output-dir "<out>"
* And I pass --move-if-fit
* And I run vcrunch
* Then "<src>" is moved to "<out>"
* And ".job.json" records "<src>" as done
