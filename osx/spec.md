# osx scripts

## Scenario: install the Podman machine environment
* When I run install
* Then Homebrew is installed
* And Podman is installed
* And the com.nashspence.scripts Podman machine exists
* And wrappers and tools are linked into ~/bin
* And the Podman Machine launch agent is loaded
* And the On Mount launch agent is loaded
* And ~/bin is added to the shell PATH
* And a Shortcuts PATH snippet is created

## Scenario: uninstall the Podman machine environment
* Given install has been run
* When I pass "--uninstall"
* And I run install
* Then wrappers and tools are removed from ~/bin
* And the Podman Machine launch agent is removed
* And the On Mount launch agent is removed
* And the Shortcuts PATH snippet is removed
* And the Podman machine is removed
* And ~/bin is removed from the shell PATH

## Scenario: wake the Podman machine on demand
* Given the Podman Machine agent is running
* When I touch the Podman socket
* Then the machine starts

## Scenario: stop an idle Podman machine
* When I run scripts-idle with a timeout
* Then the machine stops after that timeout

## Scenario: burn an ISO image
* When I run burniso with an image path
* Then the image is written to media with hdiutil

## Scenario: build and run a Containerfile
* When I run run-podman-script with "-f" and a directory path
* Then the container builds and runs without affecting the default machine

## Scenario: run a released container image
* Given a release.yaml describing a released image
* When I run run-podman-script with "-f" and a directory path and "-r" and the release.yaml path
* Then the released container runs without building

## Scenario: run a released container image without a Containerfile
* Given a release.yaml describing a released image
* When I run run-podman-script with "-r" and a release.yaml path
* Then the released container runs without building
