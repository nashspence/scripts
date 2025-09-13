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
* When I run burniso
* And I pass "--speed"
* And I pass "4"
* And I pass "--no-verify"
* And I pass "--test"
* And I pass "--eject"
* And I pass "--verbose"
* And I pass "--dry-run"
* And I pass an image path
* Then the image is written to media with hdiutil

## Scenario: burn an ISO image without ejecting
* When I run burniso
* And I pass "--no-eject"
* And I pass an image path
* Then the media is not ejected

## Scenario: build and run a Containerfile
* When I run podman-scripts-machine with "run", "-f", and a directory path
* Then the container builds and runs without affecting the default machine

## Scenario: run a released container image
* Given a release.yaml describing a released image
* When I run podman-scripts-machine with "run", "-f" and a directory path and "-r" and the release.yaml path
* Then the released container runs without building

## Scenario: run a released container image without a Containerfile
* Given a release.yaml describing a released image
* When I run podman-scripts-machine with "run", "-r" and a release.yaml path
* Then the released container runs without building

## Scenario: run an existing image without build options
* When I run podman-scripts-machine with "run" and an image name
* And I pass a command to execute
* Then Podman runs the image on the machine without "--file" or "--release"

## Scenario: run another Podman subcommand
* When I run podman-scripts-machine with "secret" and "ls"
* Then Podman lists secrets from the machine

## Scenario: enable verbose logging
* When I run podman-scripts-machine with "--verbose", "run" and an image name
* Then detailed debug logs are printed

## Scenario: push directory contents excluding dot files
* When I run rpush
* And I pass "--ignore-dotfiles"
* And I pass "copy"
* And I pass a directory path ending with "/"
* And I pass a URL
* Then dot files are not copied to the destination

## Scenario: store and retrieve a Keychain password
* Given a password is on the clipboard
* When I run kc with "add"
* And I pass a name
* Then the password is stored under that name
* When I run kc with "get"
* And I pass the same name
* Then the password is printed
* Given another password is on the clipboard
* When I run kc with "update"
* And I pass the same name
* Then the password is updated
* When I run kc with "delete"
* And I pass the same name
* Then the password is removed
