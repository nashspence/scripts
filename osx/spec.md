# osx scripts

## Scenario: install the Podman machine environment
* When I run install
* Then Homebrew is installed
* And Podman is installed
* And the com.nashspence.scripts Podman machine exists
* And wrapper and tool directories are added to the shell PATH
* And the Podman Machine launch agent is loaded
* And the On Mount launch agent is loaded

## Scenario: uninstall the Podman machine environment
* Given install has been run
* When I pass "--uninstall"
* And I run install
* Then wrapper and tool directories are removed from the shell PATH
* And the Podman Machine launch agent is removed
* And the On Mount launch agent is removed
* And the Podman machine is removed

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
* When I run podman-script-machine with "run", "-f", and a directory path
* Then the container builds and runs without affecting the default machine

## Scenario: run a released container image
* Given a release.yaml describing a released image
* When I run podman-script-machine with "run", "-f" and a directory path and "-r" and the release.yaml path
* Then the released container runs without building

## Scenario: run a released container image without a Containerfile
* Given a release.yaml describing a released image
* When I run podman-script-machine with "run", "-r" and a release.yaml path
* Then the released container runs without building

## Scenario: run an existing image without build options
* When I run podman-script-machine with "run" and an image name
* And I pass a command to execute
* Then Podman runs the image on the machine without "--file" or "--release"

## Scenario: run another Podman subcommand
* When I run podman-script-machine with "secret" and "ls"
* Then Podman lists secrets from the machine
