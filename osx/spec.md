# osx scripts

## Scenario: manage Podman machine wrappers
* Run `pmachine`
* Wrappers are installed
* Run `pmachine --uninstall`
* Wrappers are removed

## Scenario: wake the Podman machine on demand
* Start `pmachine-waker`
* Touch the Podman socket
* The machine starts

## Scenario: stop an idle Podman machine
* Start `pmachine-idle` with an idle timeout
* The machine stops after the timeout

## Scenario: burn an ISO image
* Run `burniso <image.iso>`
* The image is written to media with `hdiutil`

## Scenario: build and run a Containerfile
* Run `dr <path>`
* The container builds and runs without affecting the default machine

