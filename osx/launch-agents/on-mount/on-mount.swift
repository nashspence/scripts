import AppKit
import Foundation

let marker = ".com.nashspence.scripts.on-mount.id"
let onmountDir = FileManager.default.homeDirectoryForCurrentUser.path + "/git/osx-on-mount"

@inline(__always) func log(_ s: String) {
    FileHandle.standardOutput.write((s + "\n").data(using: .utf8)!)
}
@inline(__always) func warn(_ s: String) {
    FileHandle.standardError.write(("[WARN] " + s + "\n").data(using: .utf8)!)
}
@inline(__always) func shQuote(_ s: String) -> String {
    "'" + s.replacingOccurrences(of: "'", with: "'\\''") + "'"
}

func maybeRun(for volumeURL: URL) {
    let markerURL = volumeURL.appendingPathComponent(marker)

    guard
        let data = try? Data(contentsOf: markerURL),
        let name = String(data: data, encoding: .utf8)?
            .split(separator: "\n").first.map(String.init)?
            .trimmingCharacters(in: .whitespacesAndNewlines),
        !name.isEmpty
    else { return }

    let prog = URL(fileURLWithPath: onmountDir).appendingPathComponent(name).path
    guard FileManager.default.isExecutableFile(atPath: prog) else {
        warn("Executable not found: \(prog)")
        return
    }

    log("Mount: \(volumeURL.path) → \(prog)")

    let script = """
    tell application "Terminal"
      activate
      do script "exec \(shQuote(prog)) \(shQuote(volumeURL.path))"
    end tell
    """
    if let asObj = NSAppleScript(source: script) {
        var err: NSDictionary?
        _ = asObj.executeAndReturnError(&err)
        if let e = err { warn("AppleScript error: \(e)") }
    } else {
        warn("Failed to construct AppleScript.")
    }
}

// --- Top-level startup code (requires NO -parse-as-library) ---
let nc = NSWorkspace.shared.notificationCenter
var token: NSObjectProtocol?
token = nc.addObserver(forName: NSWorkspace.didMountNotification,
                       object: nil, queue: .main) { note in
    let uAny = note.userInfo?[NSWorkspace.volumeURLUserInfoKey] ??
               note.userInfo?["NSWorkspaceVolumeURLKey"]
    if let url = uAny as? URL {
        log("DidMount: \(url.path)")
        maybeRun(for: url)
    } else {
        warn("DidMount without URL in userInfo")
    }
}

log("on-mount listener started (pid \(getpid()))")
RunLoop.main.run()