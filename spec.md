# Specification

Scenario: use-machine reports the machine name once the LaunchAgent is ready
  Given the use-machine CLI is installed
  And the LaunchAgent socket is listening
  And a background process with PID <pid> is running
  When I run `use-machine <pid>`
  Then the command prints `<machine>`
  And the CLI exits successfully
  And the LaunchAgent keeps the socket open until <pid> exits
  And the LaunchAgent stops the Podman machine after the last hold releases

Scenario: install.sh installs the LaunchAgent for the current user
  Given the repository files are present
  When I run `./install.sh`
  Then the script copies the CLI into `~/Library/Application Support/use-machine/bin`
  And it writes the LaunchAgent plist to `~/Library/LaunchAgents/com.nashspence.use-machine.podman-machine.plist`
  And it loads the LaunchAgent with launchctl
  And it creates a `~/bin/use-machine` symlink

Scenario: install.sh removes the LaunchAgent when asked
  Given use-machine is installed
  When I run `./install.sh --uninstall`
  Then the LaunchAgent is unloaded
  And the plist is removed from `~/Library/LaunchAgents`
  And the installation directory is deleted
