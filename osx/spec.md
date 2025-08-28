# osx scripts

## Scenario: manage Podman machine wrappers
* When I run pmachine
* Then wrappers are installed
* When I run pmachine --uninstall
* Then wrappers are removed

## Scenario: wake the Podman machine on demand
* Given pmachine-waker is running
* When I touch the Podman socket
* Then the machine starts

## Scenario: stop an idle Podman machine
* When I run pmachine-idle with a timeout
* Then the machine stops after that timeout

## Scenario: burn an ISO image
* When I run burniso with an image path
* Then the image is written to media with hdiutil

## Scenario: build and run a Containerfile
* When I run dr with a directory path
* Then the container builds and runs without affecting the default machine

## Scenario: run a released container image
* Given a release.yaml describing a released image
* When I run dr with a directory path and release.yaml
* Then the released container runs without building
